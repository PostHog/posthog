import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.llm.system_one import SystemOneNotConfigured, SystemOneRequestFailed
from posthog.temporal.cimd_provisioning_review.benchmark import (
    CASES_PATH,
    BenchmarkCase,
    JudgedCase,
    ThresholdScore,
    load_cases,
    score,
    sweep,
)
from posthog.temporal.cimd_provisioning_review.judgment import (
    JUDGE_MODEL,
    RESEARCH_THRESHOLDS,
    SCREEN_THRESHOLDS,
    Thresholds,
    judge,
)
from posthog.temporal.cimd_provisioning_review.research import research_domain
from posthog.temporal.cimd_provisioning_review.types import ReviewOutcome


def _probability(value: float | None) -> str:
    return "  -  " if value is None else f"{value:.3f}"


def _describe(thresholds: Thresholds) -> str:
    return (
        f"accept legitimate >= {thresholds.accept_legitimate_at_least}, "
        f"malicious <= {thresholds.accept_malicious_at_most}; "
        f"reject malicious >= {thresholds.reject_malicious_at_least}"
    )


def _row(result: ThresholdScore) -> str:
    return (
        f"{_describe(result.thresholds)} | accepted {result.accepted}, rejected {result.rejected}, "
        f"escalated {result.escalated} | false accepts {result.false_accepts}, false rejects {result.false_rejects}"
    )


class Command(BaseCommand):
    help = "Run labeled partner registrations through Jev and report the review thresholds that keep them safe."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--cases", type=Path, default=CASES_PATH, help="YAML file of labeled cases.")
        parser.add_argument(
            "--research",
            action="store_true",
            help="Also collect live Firecrawl evidence per case and score the research stage.",
        )
        parser.add_argument("--out", type=Path, help="Write every judgment to this JSON file.")
        parser.add_argument("--top", type=int, default=5, help="How many threshold sets to print per stage.")

    def handle(self, *args: Any, **options: Any) -> None:
        cases = load_cases(options["cases"])
        self.stdout.write(f"{len(cases)} cases, asking {JUDGE_MODEL}")

        screen: list[JudgedCase] = []
        research: list[JudgedCase] = []
        for case in cases:
            screen.append(JudgedCase(case=case, judgment=self._judge(case)))
            if options["research"]:
                evidence = research_domain(
                    case.registration.domain, homepage_url=case.registration.homepage_url()
                ).to_json()
                research.append(JudgedCase(case=case, judgment=self._judge(case, evidence=evidence)))

        self._report("Screen", screen, SCREEN_THRESHOLDS, ReviewOutcome.RESEARCH, options["top"])
        if research:
            self._report("Research", research, RESEARCH_THRESHOLDS, ReviewOutcome.NEEDS_HUMAN, options["top"])

        if options["out"]:
            stages = {"screen": screen, "research": research}
            options["out"].write_text(
                json.dumps(
                    {
                        stage: [
                            {
                                "name": item.case.name,
                                "label": item.case.label.value,
                                "model": item.judgment.model,
                                "legitimate": item.judgment.legitimate,
                                "malicious": item.judgment.malicious,
                            }
                            for item in judged
                        ]
                        for stage, judged in stages.items()
                    },
                    indent=2,
                )
            )

    def _judge(self, case: BenchmarkCase, *, evidence: Any = None):
        try:
            return judge(case.registration, evidence=evidence)
        except SystemOneNotConfigured as error:
            raise CommandError(f"{error}. Set AI_GATEWAY_URL and AI_GATEWAY_API_KEY in .env.local.") from error
        except SystemOneRequestFailed as error:
            raise CommandError(f"Jev failed on {case.name}: {error}") from error

    def _report(
        self, stage: str, judged: list[JudgedCase], current: Thresholds, unsettled: ReviewOutcome, top: int
    ) -> None:
        self.stdout.write(f"\n{stage}")
        for item in judged:
            outcome = score([item], current, unsettled=unsettled)
            verdict = "accept" if outcome.accepted else "reject" if outcome.rejected else "escalate"
            wrong = outcome.false_accepts or outcome.false_rejects
            self.stdout.write(
                f"  {'✗' if wrong else ' '} {item.case.name:<34} {item.case.label.value:<10} "
                f"legitimate {_probability(item.judgment.legitimate)}  malicious {_probability(item.judgment.malicious)}  "
                f"-> {verdict}"
            )
        self.stdout.write(f"  Current: {_row(score(judged, current, unsettled=unsettled))}")
        ranked = sweep(judged, unsettled=unsettled)
        self.stdout.write("  Best:")
        for result in ranked[:top]:
            self.stdout.write(f"    {'safe  ' if result.safe else 'UNSAFE'} {_row(result)}")
