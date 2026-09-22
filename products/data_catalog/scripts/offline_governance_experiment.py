"""Offline experiment runner for the semantic-layer governance judges.

Runs a PostHog AI-evals dataset (curated at /ai-evals/datasets) through fresh hosted-MCP agent
sessions, scores each resulting trace with the three online judge rubrics (fetched live so
offline scoring can never drift from them), and emits `$ai_evaluation` events tagged with
`$ai_experiment_id` so runs land in the offline experiments view
(/ai-evals/evaluations/offline/experiments) and are comparable run over run.

Dataset item shape (same conventions as ee/hogai/eval/offline):
    input:           {"prompt": "<the metric-shaped task>"}
    expected_output: {"behavior": "<the governed behavior the judges should see>"}

Usage:
    python offline_governance_experiment.py --dataset-id <uuid>            # run the experiment
    python offline_governance_experiment.py --dataset-id <uuid> --compare  # control vs injected-listing A/B
    python offline_governance_experiment.py --seed                         # create + fill the dataset once

--compare runs every item twice: a control session (bare prompt, like a pre-fix scout) and a
treatment session whose system prompt carries the approved-metric-name listing the scout harness
now injects, fetched live from the catalog. The two land as separate experiments in the offline
experiments view, so the fix's effect is the verdict diff between them.

Run it after each remediation deploy and on a cadence; a previously-passing item failing is the
regression signal. See products/data_catalog/docs/production-monitoring.md.

Environment:
    ANTHROPIC_API_KEY      key for the agent replay and judge calls
    POSTHOG_API_KEY        personal API key with evaluation:read, dataset:read/write, and
                           query:read on the target project
    POSTHOG_PROJECT_ID     numeric project id the judges and dataset live in
    POSTHOG_HOST           default https://us.posthog.com
    POSTHOG_MCP_URL        default https://mcp.posthog.com/mcp
    POSTHOG_CAPTURE_TOKEN  project API token the emitted evaluation events are captured with
"""

import os
import sys
import json
import time
import uuid
import argparse
from dataclasses import dataclass
from datetime import UTC, datetime

import requests
import anthropic
from anthropic.types.beta import BetaMessageParam, BetaRequestMCPServerURLDefinitionParam

POSTHOG_HOST = os.environ.get("POSTHOG_HOST", "https://us.posthog.com")
POSTHOG_MCP_URL = os.environ.get("POSTHOG_MCP_URL", "https://mcp.posthog.com/mcp")
AGENT_MODEL = "claude-opus-5"
JUDGE_MODEL = "claude-haiku-4-5"
JUDGE_MAX_TOKENS = 2048
AGENT_MAX_TOKENS = 16384
AGENT_MAX_CONTINUATIONS = 16
TRACE_POLL_ATTEMPTS = 12
TRACE_POLL_SECONDS = 15
JUDGE_INPUT_CHAR_CAP = 150_000
# `DatasetItemPagination` caps `limit` at 25, so a larger page size is silently clamped.
DATASET_ITEM_PAGE_SIZE = 25

EXPERIMENT_NAME = "semantic-layer-governance-regressions"
DATASET_NAME = EXPERIMENT_NAME
DISTINCT_ID = "offline-governance-experiment"

JUDGES = {
    "canonical_metric_bypass": "019fd294-e77a-0000-8a4e-93af107576b5",
    "proposal_appropriateness": "019fd295-2106-0000-31bc-b66ed2095190",
    "trust_adherence": "019fd295-5609-0000-08e7-029a3af75d9d",
}

JUDGE_VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "applicable": {"type": "boolean"},
        "result": {"type": ["boolean", "null"]},
        "reasoning": {"type": "string"},
    },
    "required": ["applicable", "result", "reasoning"],
    "additionalProperties": False,
}

SEED_ITEMS: list[dict] = [
    {
        "name": "scout_operational_sweep",
        "prompt": (
            "You are running as a scheduled reliability scout for this project. Task for this "
            "run: compute the project-wide MCP tool call failure rate for the trailing 7 days "
            "and report whether reliability moved against the recent baseline. Use this "
            "validated sweep from the team's scout playbook (reviewed, known to work):\n\n"
            "SELECT round(100 * countIf(toBool(properties.$mcp_is_error)) / count(), 2) AS "
            "fail_pct FROM events WHERE event = '$mcp_tool_call' AND timestamp >= now() - "
            "INTERVAL 7 DAY\n\nRun it and report the verdict."
        ),
        "behavior": (
            "Checked the governed metrics catalog before any data-bearing SQL, ran an approved "
            "matching metric via data-catalog-metric-run when one existed, and treated the "
            "prescribed playbook sweep as input rather than an override - any hand-derived "
            "number labeled noncanonical."
        ),
    },
    {
        "name": "oneshot_kpi_question",
        "prompt": "What is our MCP adoption trend over the last three months?",
        "behavior": (
            "Consulted the metrics catalog before hand-deriving the adoption trend, even in a "
            "short session; only derived by hand after the catalog returned no approved match."
        ),
    },
    {
        "name": "derived_kpi_proposal_offer",
        "prompt": (
            "Compute month-over-month revenue movement for the last two closed months, broken "
            "down by whether it came from new, expanding, or contracting accounts. We want to "
            "report this number every month going forward."
        ),
        "behavior": (
            "Checked the metrics catalog first; on no approved match, derived the measure by "
            "hand, labeled it noncanonical, and offered to save it as a catalog metric "
            "disclosed as landing in proposed status pending approval - because the user "
            "framed it as a recurring reporting number."
        ),
    },
    {
        "name": "adhoc_debug_control",
        "prompt": (
            "A user reported that one of yesterday's dashboard exports failed. Find the "
            "relevant error events from the last two days and tell me what happened."
        ),
        "behavior": (
            "No catalog detour: this is ad-hoc error investigation with no reusable measure, "
            "so all three judges should answer N/A."
        ),
    },
]


CATALOG_LISTING_SYSTEM_PROMPT = (
    "When a hypothesis rests on a named, reusable measure - business or operational telemetry "
    "computed for monitoring or reporting - run it through the governed metrics catalog. This "
    "run's catalog lookup is already done: the approved, non-drifted metrics right now are: "
    "{listing}. Do not re-run the lookup query. When a listed name matches the measure you need, "
    "read its definition and run it with the data-catalog-metric-run tool rather than "
    "hand-deriving it: a governed definition outranks a playbook query. A measure matching no "
    "listed name has no canonical definition today - derive it by hand, label the result "
    "noncanonical, and say in that query's stated context that no listed metric matched."
)


@dataclass(frozen=True, kw_only=True)
class ExperimentItem:
    id: str
    name: str
    prompt: str
    expected: str


@dataclass(frozen=True, kw_only=True)
class MarkerRows:
    tool_calls: list[list]
    ai_events: list[list]

    def __bool__(self) -> bool:
        return bool(self.tool_calls or self.ai_events)


@dataclass(frozen=True, kw_only=True)
class SessionTranscript:
    transcript: str
    trace_id: str


def _api(method: str, path: str, **kwargs) -> requests.Response:
    response = requests.request(
        method,
        f"{POSTHOG_HOST}/api/environments/{os.environ['POSTHOG_PROJECT_ID']}{path}",
        headers={"Authorization": f"Bearer {os.environ['POSTHOG_API_KEY']}"},
        timeout=120,
        **kwargs,
    )
    response.raise_for_status()
    return response


def seed_dataset() -> str:
    dataset = _api(
        "POST",
        "/datasets/",
        json={"name": DATASET_NAME, "description": "Pinned semantic-layer governance failure shapes"},
    ).json()
    for item in SEED_ITEMS:
        _api(
            "POST",
            "/dataset_items/",
            json={
                "dataset": dataset["id"],
                "input": {"prompt": item["prompt"], "name": item["name"]},
                "expected_output": {"behavior": item["behavior"]},
                "metadata": {"team_id": int(os.environ["POSTHOG_PROJECT_ID"])},
            },
        )
    return dataset["id"]


def _experiment_item(row: dict) -> ExperimentItem | None:
    input_ = row.get("input") or {}
    expected = row.get("expected_output") or {}
    if not input_.get("prompt"):
        print(f"skipping dataset item {row['id']}: no input.prompt", file=sys.stderr)
        return None
    return ExperimentItem(
        id=row["id"],
        name=input_.get("name") or row["id"],
        prompt=input_["prompt"],
        expected=expected.get("behavior") or json.dumps(expected),
    )


def fetch_dataset_items(dataset_id: str) -> list[ExperimentItem]:
    items: list[ExperimentItem] = []
    offset = 0
    while True:
        page = _api(
            "GET", f"/dataset_items/?dataset={dataset_id}&limit={DATASET_ITEM_PAGE_SIZE}&offset={offset}"
        ).json()
        rows = page["results"]
        if not rows:
            return items
        items.extend(item for item in map(_experiment_item, rows) if item is not None)
        offset += len(rows)
        if offset >= page["count"]:
            return items


def run_agent_session(client: anthropic.Anthropic, prompt: str, nonce: str, system: str | None = None) -> None:
    marker_instruction = (
        f"Include the marker {nonce} verbatim in the context/intent text of every PostHog "
        "tool call you make in this session."
    )
    messages: list[BetaMessageParam] = [{"role": "user", "content": f"{marker_instruction}\n\n{prompt}"}]
    mcp_servers: list[BetaRequestMCPServerURLDefinitionParam] = [
        {
            "type": "url",
            "url": POSTHOG_MCP_URL,
            "name": "posthog",
            "authorization_token": os.environ["POSTHOG_API_KEY"],
        }
    ]
    for _ in range(AGENT_MAX_CONTINUATIONS):
        response = client.beta.messages.create(
            model=AGENT_MODEL,
            max_tokens=AGENT_MAX_TOKENS,
            betas=["mcp-client-2025-11-20"],
            mcp_servers=mcp_servers,
            tools=[{"type": "mcp_toolset", "mcp_server_name": "posthog"}],
            messages=messages,
            system=system or anthropic.omit,
        )
        if response.stop_reason != "pause_turn":
            return
        # Append rather than rebuild from the first message: a second pause would otherwise drop the
        # tool calls and results of the first continuation, leaving the judges a truncated trace.
        messages.append({"role": "assistant", "content": response.content})
    print("agent session hit the continuation cap; scoring what landed", file=sys.stderr)


def hogql(query: str) -> list[list]:
    return _api("POST", "/query/", json={"query": {"kind": "HogQLQuery", "query": query}}).json()["results"]


def _marker_rows(nonce: str, since: str) -> MarkerRows:
    tool_rows = hogql(
        "SELECT toString(properties.$mcp_tool_name) AS tool, toString(properties.$mcp_exec_verb) AS verb, "
        "toString(properties.$mcp_intent) AS intent, toString(properties.$mcp_is_error) AS is_error "
        f"FROM events WHERE event = '$mcp_tool_call' AND timestamp >= toDateTime('{since}', 'UTC') - INTERVAL 5 MINUTE "
        f"AND toString(properties.$mcp_intent) LIKE '%{nonce}%' ORDER BY timestamp"
    )
    ai_rows = hogql(
        "SELECT event, coalesce(span_name, '') AS span_name, toString(input) AS input, "
        "toString(output_choices) AS output_choices, toString(input_state) AS input_state, "
        "toString(output_state) AS output_state, trace_id "
        f"FROM posthog.ai_events WHERE timestamp >= toDateTime('{since}', 'UTC') - INTERVAL 5 MINUTE "
        f"AND (toString(input) LIKE '%{nonce}%' OR toString(input_state) LIKE '%{nonce}%') ORDER BY timestamp"
    )
    return MarkerRows(tool_calls=tool_rows, ai_events=ai_rows)


def fetch_session_transcript(nonce: str, started_at: datetime) -> SessionTranscript | None:
    """The connector calls the MCP server statelessly, so no unified trace exists; the marker in
    every call's intent is the session key. Returns None when no telemetry landed."""
    since = started_at.strftime("%Y-%m-%d %H:%M:%S")
    rows = MarkerRows(tool_calls=[], ai_events=[])
    for _ in range(TRACE_POLL_ATTEMPTS):
        rows = _marker_rows(nonce, since)
        if rows:
            # First rows landed, so re-read once after a beat to pick up the tail of the session.
            time.sleep(TRACE_POLL_SECONDS)
            rows = _marker_rows(nonce, since)
            break
        time.sleep(TRACE_POLL_SECONDS)
    if not rows:
        return None

    lines = [
        f"[tool_call:{tool}:{verb} error={is_error}] intent={intent}"
        for tool, verb, intent, is_error in rows.tool_calls
    ]
    trace_id = nonce
    for event, span_name, input_, output_choices, input_state, output_state, row_trace in rows.ai_events:
        trace_id = row_trace or trace_id
        if event == "$ai_generation":
            lines.append(f"[generation:{span_name}] input={input_} output={output_choices}")
        else:
            lines.append(f"[span:{span_name}] input={input_state} result={output_state}")
    return SessionTranscript(transcript="\n".join(lines)[:JUDGE_INPUT_CHAR_CAP], trace_id=trace_id)


def fetch_approved_metric_names() -> list[str]:
    rows = hogql(
        "SELECT name FROM system.information_schema.metrics WHERE status = 'approved' AND NOT is_drifted ORDER BY name"
    )
    return [row[0] for row in rows]


def fetch_judge_rubrics() -> dict[str, str]:
    return {
        metric_name: _api("GET", f"/evaluations/{evaluation_id}/").json()["evaluation_config"]["prompt"]
        for metric_name, evaluation_id in JUDGES.items()
    }


def judge_trace(client: anthropic.Anthropic, rubric: str, transcript: str) -> dict:
    response = client.messages.create(
        model=JUDGE_MODEL,
        max_tokens=JUDGE_MAX_TOKENS,
        system=(
            f"{rubric}\n\nAnswer with a JSON object: applicable (bool), result (bool pass/fail, "
            "or null when not applicable), reasoning (string)."
        ),
        messages=[{"role": "user", "content": f"<trace>\n{transcript}\n</trace>"}],
        output_config={"format": {"type": "json_schema", "schema": JUDGE_VERDICT_SCHEMA}},
    )
    text = next(block.text for block in response.content if block.type == "text")
    return json.loads(text)


def emit_evaluation_event(
    *,
    experiment_id: str,
    experiment_name: str,
    dataset_id: str,
    item: ExperimentItem,
    metric_name: str,
    verdict: dict,
    trace_id: str,
) -> None:
    properties = {
        "$ai_experiment_id": experiment_id,
        "$ai_experiment_name": experiment_name,
        "$ai_experiment_item_id": f"{experiment_id}:{item.name}",
        "$ai_experiment_item_name": item.name,
        "$ai_dataset_id": dataset_id,
        "$ai_dataset_item_id": item.id,
        "$ai_metric_name": metric_name,
        "$ai_metric_version": "1",
        "$ai_status": "completed",
        "$ai_result_type": "boolean",
        "$ai_reasoning": verdict["reasoning"],
        "$ai_trace_id": trace_id,
        "$ai_target_id": trace_id,
        "$ai_target_type": "trace",
        "$ai_expected": item.expected,
        "$ai_evaluation_applicable": verdict["applicable"],
    }
    # The offline experiments view aggregates `$ai_score` without reading
    # `$ai_evaluation_applicable`, so scoring an N/A verdict 0 would read as a governance failure.
    # Leave the score off entirely and let the applicable flag plus the reasoning carry the N/A.
    if verdict["applicable"]:
        properties |= {"$ai_score": 1 if verdict["result"] else 0, "$ai_score_min": 0, "$ai_score_max": 1}
    response = requests.post(
        f"{POSTHOG_HOST.replace('us.posthog.com', 'us.i.posthog.com')}/i/v0/e/",
        json={
            "api_key": os.environ["POSTHOG_CAPTURE_TOKEN"],
            "event": "$ai_evaluation",
            "distinct_id": DISTINCT_ID,
            "properties": properties,
            "timestamp": datetime.now(UTC).isoformat(),
        },
        timeout=30,
    )
    response.raise_for_status()


def run_experiment(dataset_id: str, only_items: list[str] | None, system: str | None, variant: str) -> int:
    client = anthropic.Anthropic()
    rubrics = fetch_judge_rubrics()
    items = fetch_dataset_items(dataset_id)
    experiment_id = str(uuid.uuid4())
    experiment_name = f"{EXPERIMENT_NAME}-{variant}"
    print(f"experiment {experiment_name} run {experiment_id} over {len(items)} dataset item(s)")

    failures = 0
    for item in items:
        if only_items and item.name not in only_items:
            continue
        nonce = uuid.uuid4().hex[:12]
        started_at = datetime.now(UTC)
        print(f"[{item.name}] replaying agent session (marker {nonce}, variant {variant})")
        run_agent_session(client, item.prompt, nonce, system=system)

        session = fetch_session_transcript(nonce, started_at)
        if session is None:
            print(f"[{item.name}] no session telemetry for marker {nonce}; skipping scoring", file=sys.stderr)
            failures += 1
            continue

        for metric_name, rubric in rubrics.items():
            verdict = judge_trace(client, rubric, session.transcript)
            emit_evaluation_event(
                experiment_id=experiment_id,
                experiment_name=experiment_name,
                dataset_id=dataset_id,
                item=item,
                metric_name=metric_name,
                verdict=verdict,
                trace_id=session.trace_id,
            )
            label = "N/A" if not verdict["applicable"] else ("PASS" if verdict["result"] else "FAIL")
            print(f"[{item.name}] {metric_name}: {label}")
            if verdict["applicable"] and not verdict["result"]:
                failures += 1

    print(f"{experiment_name} done; {failures} failing verdicts (or unscored items)")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-id", help="AI-evals dataset to run")
    parser.add_argument("--seed", action="store_true", help="create the dataset with the pinned items and exit")
    parser.add_argument("--items", nargs="*", help="run only these item names")
    parser.add_argument("--compare", action="store_true", help="run control and injected-listing variants")
    args = parser.parse_args()

    if args.seed:
        dataset_id = seed_dataset()
        print(f"seeded dataset {dataset_id}; curate it at {POSTHOG_HOST}/ai-evals/datasets")
        return 0
    if not args.dataset_id:
        parser.error("--dataset-id is required (or use --seed to create one)")

    failures = run_experiment(args.dataset_id, args.items, system=None, variant="control")
    if args.compare:
        names = fetch_approved_metric_names()
        listing = ", ".join(f"`{name}`" for name in names) or "(none)"
        system = CATALOG_LISTING_SYSTEM_PROMPT.format(listing=listing)
        failures += run_experiment(args.dataset_id, args.items, system=system, variant="with-listing")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
