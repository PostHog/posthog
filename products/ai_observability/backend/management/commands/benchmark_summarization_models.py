"""Compare summarization models on real traces: cost, latency, and the summary text itself.

The batch clustering pipeline summarizes every sampled trace with one LLM call, so the model
choice sets both the pipeline's largest cost line and the quality of every downstream cluster.
Clustering consumes a summary twice, once as an embedding that decides the cluster boundary and
once as text that the labeling agent reads, so a model swap has to be judged on output text and
not on price alone.

The JSON report holds customer trace content. Keep it out of the repository, out of pull request
descriptions, and out of screenshots.

Reading traces needs ClickHouse, while calling the models needs a gateway credential. Where one
machine has both, run it in one step. Where they are split, export the prompts on the machine
that reaches ClickHouse and benchmark them on the machine that holds the credential:

    python manage.py benchmark_summarization_models --team-id 2 --limit 30

    python manage.py benchmark_summarization_models --team-id 2 --export-prompts prompts.json
    python manage.py benchmark_summarization_models --team-id 2 --trace-file prompts.json
"""

import json
import time
import statistics
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from django.core.management.base import BaseCommand, CommandError

from openai import OpenAI
from openai.types.chat import ChatCompletion

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import build_openai_client, team_distinct_id
from posthog.models.team import Team
from posthog.temporal.ai_observability.trace_summarization.queries import fetch_trace
from posthog.temporal.ai_observability.trace_summarization.utils import format_datetime_for_clickhouse

from products.ai_observability.backend.summarization.budget import bounded_text_repr, text_repr_budget
from products.ai_observability.backend.summarization.constants import SUMMARIZATION_FLEX_TIMEOUT
from products.ai_observability.backend.summarization.llm.openai import (
    SUMMARIZATION_RESPONSE_FORMAT,
    build_summarization_messages,
)
from products.ai_observability.backend.summarization.llm.schema import SummarizationResponse
from products.ai_observability.backend.summarization.models import SummarizationMode
from products.ai_observability.backend.text_repr.formatters import (
    FormatterOptions,
    format_trace_text_repr,
    llm_trace_to_formatter_format,
)

ReasoningEffort = Literal["minimal", "low", "medium", "high"]

# Titles printed to the terminal. The rest stay in the JSON report so a large run is still
# readable in a shell.
TITLES_SHOWN = 10


@frozen
class TokenPrice:
    """USD per single token, as published on OpenAI's pricing page."""

    input: float
    cached_input: float
    output: float


# Keyed by the model and service tier the call actually requests, because the flex tier halves
# both the input and the output rate. A missing key makes the run fail rather than report a cost
# derived from another model's rate.
TOKEN_PRICES: dict[tuple[str, str], TokenPrice] = {
    ("gpt-4.1-nano", "standard"): TokenPrice(input=1e-7, cached_input=2.5e-8, output=4e-7),
    ("gpt-5-nano", "standard"): TokenPrice(input=5e-8, cached_input=5e-9, output=4e-7),
    ("gpt-5-nano", "flex"): TokenPrice(input=2.5e-8, cached_input=2.5e-9, output=2e-7),
}


@frozen
class Variant:
    """One model configuration under test."""

    label: str
    model: str
    tier: Literal["standard", "flex"] = "standard"
    reasoning_effort: ReasoningEffort | None = None
    timeout_s: float = 120.0


VARIANTS: dict[str, Variant] = {
    "baseline": Variant(label="baseline", model="gpt-4.1-nano"),
    "gpt5-nano": Variant(label="gpt5-nano", model="gpt-5-nano", reasoning_effort="minimal"),
    "gpt5-nano-flex": Variant(
        label="gpt5-nano-flex",
        model="gpt-5-nano",
        tier="flex",
        reasoning_effort="minimal",
        timeout_s=float(SUMMARIZATION_FLEX_TIMEOUT),
    ),
}


@frozen
class Sample:
    """A real trace to summarize, with the window its events fall in."""

    trace_id: str
    window_start: str
    window_end: str


@frozen
class CallResult:
    variant: str
    trace_id: str
    text_repr_chars: int
    ok: bool
    latency_s: float
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: float = 0.0
    served_tier: str | None = None
    title: str | None = None
    summary: dict[str, Any] | None = None
    error: str | None = None


def _price(model: str, tier: str) -> TokenPrice:
    key = (model, tier)
    if key not in TOKEN_PRICES:
        raise CommandError(f"No price for {key}. Add it to TOKEN_PRICES before benchmarking.")
    return TOKEN_PRICES[key]


def _sample_traces(team: Team, days: int, limit: int) -> list[Sample]:
    """Pick traces the pipeline already summarized.

    Those traces passed the pipeline's event-count and raw-size guards, so the benchmark measures
    the population the pipeline really sends rather than traces it would have skipped. Ordering by
    a hash of the trace id spreads the sample over the whole window and keeps it reproducible
    across runs.
    """
    after = format_datetime_for_clickhouse((datetime.now(UTC) - timedelta(days=days)).isoformat())
    response = execute_hogql_query(
        """
        SELECT properties.$ai_trace_id AS trace_id, timestamp
        FROM events
        WHERE event = '$ai_trace_summary'
          AND timestamp >= {after}
          AND properties.$ai_trace_id != ''
        ORDER BY cityHash64(properties.$ai_trace_id)
        LIMIT {limit}
        """,
        team=team,
        placeholders={"after": ast.Constant(value=after), "limit": ast.Constant(value=limit)},
    )

    samples = []
    for trace_id, summary_timestamp in response.results or []:
        # A summary is emitted up to an hour and a half after its trace starts, and the trace
        # itself can span a while. Widen generously; the trace read filters on trace_id, so a
        # wider window costs scan time rather than correctness.
        samples.append(
            Sample(
                trace_id=trace_id,
                window_start=format_datetime_for_clickhouse((summary_timestamp - timedelta(hours=4)).isoformat()),
                window_end=format_datetime_for_clickhouse((summary_timestamp + timedelta(minutes=30)).isoformat()),
            )
        )
    return samples


def _build_text_reprs(team: Team, sample: Sample, budgets: set[int]) -> dict[int, str] | None:
    """Render one trace the way `fetch_and_format_activity` does, once per character budget.

    Reads the trace once and formats it repeatedly, because the ClickHouse read dominates the
    cost of this step while formatting is in-process.
    """
    llm_trace = fetch_trace(team, sample.trace_id, sample.window_start, sample.window_end)
    if llm_trace is None:
        return None

    trace_dict, hierarchy = llm_trace_to_formatter_format(llm_trace)
    rendered = {}
    for budget in budgets:
        options: FormatterOptions = {
            "include_line_numbers": True,
            "truncated": True,
            "include_markers": False,
            "collapsed": False,
            "max_length": budget,
        }
        text_repr, _ = format_trace_text_repr(trace=trace_dict, hierarchy=hierarchy, options=options)
        rendered[budget] = text_repr
    return rendered


def _call(
    client: OpenAI,
    variant: Variant,
    trace_id: str,
    text_repr: str,
    mode: SummarizationMode,
    distinct_id: str,
) -> CallResult:
    extra: dict[str, Any] = {}
    if variant.reasoning_effort is not None:
        extra["reasoning_effort"] = variant.reasoning_effort
    if variant.tier == "flex":
        extra["service_tier"] = "flex"

    started = time.monotonic()
    try:
        response: ChatCompletion = client.chat.completions.create(
            model=variant.model,
            messages=build_summarization_messages(text_repr, mode),
            user=distinct_id,
            timeout=variant.timeout_s,
            response_format=SUMMARIZATION_RESPONSE_FORMAT,
            **extra,
        )
    except Exception as e:
        return CallResult(
            variant=variant.label,
            trace_id=trace_id,
            text_repr_chars=len(text_repr),
            ok=False,
            latency_s=time.monotonic() - started,
            error=f"{type(e).__name__}: {e}",
        )
    latency_s = time.monotonic() - started

    usage = response.usage
    input_tokens = usage.prompt_tokens if usage else 0
    output_tokens = usage.completion_tokens if usage else 0
    cached = usage.prompt_tokens_details.cached_tokens if usage and usage.prompt_tokens_details else 0
    reasoning = usage.completion_tokens_details.reasoning_tokens if usage and usage.completion_tokens_details else 0
    cached = cached or 0
    reasoning = reasoning or 0

    # OpenAI can decline a flex request and serve it at the standard tier instead, and it reports
    # the tier it used on the response. Price on that value, so a run where flex capacity was
    # short does not report a discount it never received.
    priced_tier = "flex" if response.service_tier == "flex" else "standard"
    price = _price(variant.model, priced_tier)
    # OpenAI reports cached tokens as a subset of prompt_tokens, so bill the remainder at the
    # full input rate. Reasoning tokens are already inside completion_tokens.
    cost = max(0, input_tokens - cached) * price.input + cached * price.cached_input + output_tokens * price.output

    content = response.choices[0].message.content or ""
    try:
        parsed = SummarizationResponse.model_validate_json(content)
    except Exception as e:
        return CallResult(
            variant=variant.label,
            trace_id=trace_id,
            text_repr_chars=len(text_repr),
            ok=False,
            latency_s=latency_s,
            input_tokens=input_tokens,
            cached_input_tokens=cached,
            output_tokens=output_tokens,
            reasoning_tokens=reasoning,
            cost_usd=cost,
            served_tier=response.service_tier,
            error=f"unparseable output: {type(e).__name__}: {e}",
        )

    return CallResult(
        variant=variant.label,
        trace_id=trace_id,
        text_repr_chars=len(text_repr),
        ok=True,
        latency_s=latency_s,
        input_tokens=input_tokens,
        cached_input_tokens=cached,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning,
        cost_usd=cost,
        served_tier=response.service_tier,
        title=parsed.title,
        summary=parsed.model_dump(),
    )


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


class Command(BaseCommand):
    help = "Compare summarization models on real traces for cost, latency, and summary text."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--team-id",
            type=int,
            required=True,
            help="Team whose traces to summarize. With --trace-file it only labels the spend.",
        )
        parser.add_argument(
            "--trace-file",
            default=None,
            help=(
                "JSON list of {trace_id, text_repr} to summarize instead of reading ClickHouse. "
                "Lets the benchmark run where the traces are unreachable but a gateway credential exists."
            ),
        )
        parser.add_argument(
            "--export-prompts",
            default=None,
            help="Write the sampled prompts to this path and exit without calling any model.",
        )
        parser.add_argument("--limit", type=int, default=30, help="Number of traces to sample.")
        parser.add_argument("--days", type=int, default=3, help="How far back to sample traces from.")
        parser.add_argument("--concurrency", type=int, default=4, help="Parallel LLM calls.")
        parser.add_argument(
            "--mode",
            default=SummarizationMode.DETAILED.value,
            choices=[m.value for m in SummarizationMode],
            help="Summary detail level. The batch pipeline uses detailed.",
        )
        parser.add_argument(
            "--variant",
            action="append",
            dest="variants",
            choices=sorted(VARIANTS),
            help="Repeatable. Defaults to every variant.",
        )
        parser.add_argument("--out", default=None, help="Path for the JSON report.")

    def handle(self, *args: Any, **options: Any) -> None:
        selected = [VARIANTS[name] for name in (options["variants"] or sorted(VARIANTS))]
        mode = SummarizationMode(options["mode"])
        team_id = options["team_id"]

        # Each model has its own context window, so a smaller window means the trace is sampled
        # down harder before the model ever sees it. Hold one rendering per distinct budget so
        # the report shows whether that difference bit.
        budgets = {variant.model: text_repr_budget(variant.model) for variant in selected}

        if options["export_prompts"]:
            self._export_prompts(Path(options["export_prompts"]), team_id, budgets, options)
            return

        if options["trace_file"]:
            trace_ids, text_reprs = self._load_trace_file(Path(options["trace_file"]), set(budgets.values()))
        else:
            trace_ids, text_reprs = self._read_traces(team_id, budgets, options)

        distinct_id = team_distinct_id(team_id)
        clients = {
            variant.label: build_openai_client(
                "llma_summarization",
                # A distinct tag keeps benchmark spend out of the aio_summarization cost line.
                ai_product="aio_summarization_benchmark",
                properties={"team_id": str(team_id)},
                distinct_id=distinct_id,
            )
            for variant in selected
        }

        jobs = [
            (variant, trace_id, text_reprs[(trace_id, budgets[variant.model])])
            for variant in selected
            for trace_id in trace_ids
            if (trace_id, budgets[variant.model]) in text_reprs
        ]
        if not jobs:
            raise CommandError("No trace rendered into a prompt, so there is nothing to summarize.")
        self.stdout.write(f"Running {len(jobs)} calls across {len(selected)} variants")

        with ThreadPoolExecutor(max_workers=options["concurrency"]) as pool:
            results = list(
                pool.map(
                    lambda job: _call(clients[job[0].label], job[0], job[1], job[2], mode, distinct_id),
                    jobs,
                )
            )

        self._report(results, selected)
        self._write_report(results, options["out"], team_id)

    def _export_prompts(self, path: Path, team_id: int, budgets: dict[str, int], options: dict[str, Any]) -> None:
        """Render the sampled prompts and write them for a later --trace-file run.

        Exports at the largest budget under test so the benchmark can still reduce each prompt to
        a smaller model's window later. Splitting the run this way lets the ClickHouse read happen
        where the traces live and the model calls happen where a credential lives.
        """
        largest = max(budgets.values())
        trace_ids, text_reprs = self._read_traces(team_id, {"export": largest}, options)
        entries = [{"trace_id": trace_id, "text_repr": text_reprs[(trace_id, largest)]} for trace_id in trace_ids]
        path.write_text(json.dumps(entries, indent=2))
        self.stdout.write(
            self.style.WARNING(
                f"Wrote {len(entries)} prompts to {path}. They contain trace content, so treat the "
                "file as customer data."
            )
        )

    def _read_traces(
        self, team_id: int, budgets: dict[str, int], options: dict[str, Any]
    ) -> tuple[list[str], dict[tuple[str, int], str]]:
        """Sample traces from ClickHouse and render each one at every model's budget."""
        team = Team.objects.filter(id=team_id).first()
        if team is None:
            raise CommandError(f"No team with id {team_id}")

        samples = _sample_traces(team, days=options["days"], limit=options["limit"])
        if not samples:
            raise CommandError(
                f"No $ai_trace_summary events for team {team_id} in the last {options['days']} days. "
                "Pick a team the batch pipeline already runs against, or supply --trace-file."
            )
        self.stdout.write(f"Sampled {len(samples)} traces from team {team_id}")

        text_reprs: dict[tuple[str, int], str] = {}
        rendered_ids = []
        skipped = 0
        for sample in samples:
            rendered = _build_text_reprs(team, sample, set(budgets.values()))
            if rendered is None:
                skipped += 1
                continue
            rendered_ids.append(sample.trace_id)
            for budget, text_repr in rendered.items():
                text_reprs[(sample.trace_id, budget)] = text_repr
        if skipped:
            self.stdout.write(f"Skipped {skipped} traces whose events fell outside the read window")
        return rendered_ids, text_reprs

    def _load_trace_file(self, path: Path, budgets: set[int]) -> tuple[list[str], dict[tuple[str, int], str]]:
        """Read prompts exported earlier, and reduce each one to every model's budget.

        The export already carries a rendered `text_repr`, so this path needs no ClickHouse and no
        Team row. Every variant sees the same source text, which is what keeps the comparison
        valid even when the export was produced somewhere other than the pipeline.
        """
        try:
            entries = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as e:
            raise CommandError(f"Could not read {path}: {e}")
        if not isinstance(entries, list):
            raise CommandError(f"{path} must hold a JSON list of objects with trace_id and text_repr.")

        text_reprs: dict[tuple[str, int], str] = {}
        trace_ids = []
        for entry in entries:
            trace_id, text_repr = entry.get("trace_id"), entry.get("text_repr")
            if not trace_id or not text_repr:
                raise CommandError(f"{path} has an entry missing trace_id or text_repr.")
            trace_ids.append(trace_id)
            for budget in budgets:
                text_reprs[(trace_id, budget)] = bounded_text_repr(text_repr, budget)
        self.stdout.write(f"Loaded {len(trace_ids)} prompts from {path}")
        return trace_ids, text_reprs

    def _report(self, results: list[CallResult], selected: list[Variant]) -> None:
        baseline_cost = None
        self.stdout.write("")
        header = f"{'variant':<16}{'ok':>5}{'fail':>6}{'p50 s':>8}{'p95 s':>8}{'in tok':>9}{'out tok':>9}{'reason':>8}{'$/1k calls':>12}"
        self.stdout.write(header)
        self.stdout.write("-" * len(header))

        for variant in selected:
            rows = [r for r in results if r.variant == variant.label]
            ok = [r for r in rows if r.ok]
            if not rows:
                continue
            latencies = [r.latency_s for r in ok]
            mean_cost = statistics.fmean([r.cost_usd for r in ok]) if ok else 0.0
            if variant.label == "baseline":
                baseline_cost = mean_cost
            self.stdout.write(
                f"{variant.label:<16}{len(ok):>5}{len(rows) - len(ok):>6}"
                f"{_percentile(latencies, 0.5):>8.1f}{_percentile(latencies, 0.95):>8.1f}"
                f"{statistics.fmean([r.input_tokens for r in ok]) if ok else 0:>9.0f}"
                f"{statistics.fmean([r.output_tokens for r in ok]) if ok else 0:>9.0f}"
                f"{statistics.fmean([r.reasoning_tokens for r in ok]) if ok else 0:>8.0f}"
                f"{mean_cost * 1000:>12.3f}"
            )

        if baseline_cost:
            self.stdout.write("")
            for variant in selected:
                ok = [r for r in results if r.variant == variant.label and r.ok]
                if not ok or variant.label == "baseline":
                    continue
                ratio = statistics.fmean([r.cost_usd for r in ok]) / baseline_cost
                self.stdout.write(f"{variant.label}: {(1 - ratio) * 100:.0f}% cheaper per call than baseline")

        served = {r.served_tier for r in results if r.variant == "gpt5-nano-flex" and r.ok}
        if served:
            self.stdout.write(
                f"\nTiers OpenAI actually served for gpt5-nano-flex: {sorted(t or 'unset' for t in served)}"
            )

        failures = [r for r in results if not r.ok]
        if failures:
            self.stdout.write("\nFailures:")
            for failure in failures[:10]:
                self.stdout.write(f"  {failure.variant} {failure.trace_id}: {failure.error}")

        trace_ids = list(dict.fromkeys(r.trace_id for r in results))
        self.stdout.write("\nTitles per trace. Cost is not the only question, so read these:")
        for trace_id in trace_ids[:TITLES_SHOWN]:
            self.stdout.write(f"  {trace_id}")
            for r in [r for r in results if r.trace_id == trace_id]:
                self.stdout.write(f"    {r.variant:<16} {r.title or r.error}")
        if len(trace_ids) > TITLES_SHOWN:
            self.stdout.write(f"  ... {len(trace_ids) - TITLES_SHOWN} more traces in the JSON report")

    def _write_report(self, results: list[CallResult], out: str | None, team_id: int) -> None:
        path = Path(out) if out else Path(f"summarization-benchmark-team-{team_id}.json")
        path.write_text(json.dumps([asdict(r) for r in results], indent=2, default=str))
        self.stdout.write(
            self.style.WARNING(
                f"\nFull summaries written to {path}. It contains customer trace content, "
                "so do not commit it or paste it into a pull request."
            )
        )
