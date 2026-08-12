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
    python offline_governance_experiment.py --dataset-id <uuid>       # run the experiment
    python offline_governance_experiment.py --seed                    # create + fill the dataset once

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

POSTHOG_HOST = os.environ.get("POSTHOG_HOST", "https://us.posthog.com")
POSTHOG_MCP_URL = os.environ.get("POSTHOG_MCP_URL", "https://mcp.posthog.com/mcp")
AGENT_MODEL = "claude-opus-5"
# The online judges run on this model; offline scoring keeps parity so verdicts are comparable.
JUDGE_MODEL = "claude-haiku-4-5"
JUDGE_MAX_TOKENS = 2048
AGENT_MAX_TOKENS = 8192
AGENT_MAX_CONTINUATIONS = 8
TRACE_POLL_ATTEMPTS = 12
TRACE_POLL_SECONDS = 15
# The online judges cap their input the same way; staying under it keeps verdicts comparable.
JUDGE_INPUT_CHAR_CAP = 150_000

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

# One item per failure pattern observed in production, used only by --seed; after seeding, the
# dataset in /ai-evals/datasets is the source of truth and should be curated there.
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


@dataclass(frozen=True, kw_only=True)
class ExperimentItem:
    id: str
    name: str
    prompt: str
    expected: str


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


def fetch_dataset_items(dataset_id: str) -> list[ExperimentItem]:
    rows = _api("GET", f"/dataset_items/?dataset={dataset_id}&limit=100").json()["results"]
    items = []
    for row in rows:
        input_ = row.get("input") or {}
        expected = row.get("expected_output") or {}
        if not input_.get("prompt"):
            print(f"skipping dataset item {row['id']}: no input.prompt", file=sys.stderr)
            continue
        items.append(
            ExperimentItem(
                id=row["id"],
                name=input_.get("name") or row["id"],
                prompt=input_["prompt"],
                expected=expected.get("behavior") or json.dumps(expected),
            )
        )
    return items


def run_agent_session(client: anthropic.Anthropic, prompt: str, nonce: str) -> None:
    """Drive one fresh hosted-MCP agent session; telemetry lands in the target project.

    The nonce rides in the prompt so the session's trace can be found afterwards - the MCP
    connector does not expose the server-assigned session id to the caller.
    """
    messages: list[dict] = [{"role": "user", "content": f"[run marker {nonce}] {prompt}"}]
    mcp_servers = [
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
        )
        if response.stop_reason != "pause_turn":
            return
        messages = [messages[0], {"role": "assistant", "content": response.content}]
    print("agent session hit the continuation cap; scoring what landed", file=sys.stderr)


def hogql(query: str) -> list[list]:
    return _api("POST", "/query/", json={"query": {"kind": "HogQLQuery", "query": query}}).json()["results"]


def find_trace_id(nonce: str, started_at: datetime) -> str | None:
    """The generation's input carries the run marker; ingestion can lag, so poll."""
    since = started_at.strftime("%Y-%m-%d %H:%M:%S")
    query = (
        "SELECT DISTINCT trace_id FROM posthog.ai_events "
        f"WHERE timestamp >= toDateTime('{since}', 'UTC') - INTERVAL 5 MINUTE "
        f"AND event = '$ai_generation' AND toString(input) LIKE '%{nonce}%' LIMIT 1"
    )
    for _ in range(TRACE_POLL_ATTEMPTS):
        rows = hogql(query)
        if rows:
            return rows[0][0]
        time.sleep(TRACE_POLL_SECONDS)
    return None


def fetch_trace_transcript(trace_id: str) -> str:
    rows = hogql(
        "SELECT event, coalesce(span_name, '') AS span_name, toString(input) AS input, "
        "toString(output_choices) AS output_choices, toString(input_state) AS input_state, "
        "toString(output_state) AS output_state "
        f"FROM posthog.ai_events WHERE trace_id = '{trace_id}' "
        "AND event IN ('$ai_generation', '$ai_span') ORDER BY timestamp"
    )
    lines = []
    for event, span_name, input_, output_choices, input_state, output_state in rows:
        if event == "$ai_generation":
            lines.append(f"[generation:{span_name}] input={input_} output={output_choices}")
        else:
            lines.append(f"[span:{span_name}] input={input_state} result={output_state}")
    return "\n".join(lines)[:JUDGE_INPUT_CHAR_CAP]


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
    *, experiment_id: str, dataset_id: str, item: ExperimentItem, metric_name: str, verdict: dict, trace_id: str
) -> None:
    properties = {
        "$ai_experiment_id": experiment_id,
        "$ai_experiment_name": EXPERIMENT_NAME,
        "$ai_experiment_item_id": f"{experiment_id}:{item.name}",
        "$ai_experiment_item_name": item.name,
        "$ai_dataset_id": dataset_id,
        "$ai_dataset_item_id": item.id,
        "$ai_metric_name": metric_name,
        "$ai_metric_version": "1",
        "$ai_status": "completed",
        "$ai_result_type": "boolean",
        "$ai_score": 1 if verdict["result"] else 0,
        "$ai_score_min": 0,
        "$ai_score_max": 1,
        "$ai_reasoning": verdict["reasoning"],
        "$ai_trace_id": trace_id,
        "$ai_target_id": trace_id,
        "$ai_target_type": "trace",
        "$ai_expected": item.expected,
        "$ai_evaluation_applicable": verdict["applicable"],
    }
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


def run_experiment(dataset_id: str, only_items: list[str] | None) -> int:
    client = anthropic.Anthropic()
    rubrics = fetch_judge_rubrics()
    items = fetch_dataset_items(dataset_id)
    experiment_id = str(uuid.uuid4())
    print(f"experiment {EXPERIMENT_NAME} run {experiment_id} over {len(items)} dataset item(s)")

    failures = 0
    for item in items:
        if only_items and item.name not in only_items:
            continue
        nonce = uuid.uuid4().hex[:12]
        started_at = datetime.now(UTC)
        print(f"[{item.name}] replaying agent session (marker {nonce})")
        run_agent_session(client, item.prompt, nonce)

        trace_id = find_trace_id(nonce, started_at)
        if trace_id is None:
            print(f"[{item.name}] no trace found for marker {nonce}; skipping scoring", file=sys.stderr)
            failures += 1
            continue
        transcript = fetch_trace_transcript(trace_id)

        for metric_name, rubric in rubrics.items():
            verdict = judge_trace(client, rubric, transcript)
            emit_evaluation_event(
                experiment_id=experiment_id,
                dataset_id=dataset_id,
                item=item,
                metric_name=metric_name,
                verdict=verdict,
                trace_id=trace_id,
            )
            label = "N/A" if not verdict["applicable"] else ("PASS" if verdict["result"] else "FAIL")
            print(f"[{item.name}] {metric_name}: {label}")
            if verdict["applicable"] and not verdict["result"]:
                failures += 1

    print(f"done; {failures} failing verdicts (or unscored items)")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-id", help="AI-evals dataset to run")
    parser.add_argument("--seed", action="store_true", help="create the dataset with the pinned items and exit")
    parser.add_argument("--items", nargs="*", help="run only these item names")
    args = parser.parse_args()

    if args.seed:
        dataset_id = seed_dataset()
        print(f"seeded dataset {dataset_id}; curate it at {POSTHOG_HOST}/ai-evals/datasets")
        return 0
    if not args.dataset_id:
        parser.error("--dataset-id is required (or use --seed to create one)")
    return run_experiment(args.dataset_id, args.items)


if __name__ == "__main__":
    sys.exit(main())
