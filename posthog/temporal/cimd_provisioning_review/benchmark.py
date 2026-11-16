"""Scores Jev's partner judgments against labeled cases, to pick the review thresholds.

Run it with ``python manage.py cimd_provisioning_review_benchmark``. The labeled cases live in
``benchmark_cases.yaml``. A threshold set is safe only when no malicious case is accepted and no
legitimate case is rejected; among safe sets, the one that settles the most cases without staff wins.
"""

from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum
from itertools import product
from pathlib import Path
from typing import Any

import yaml

from posthog.dataclasses import frozen
from posthog.temporal.cimd_provisioning_review.judgment import (
    PartnerJudgment,
    PartnerRegistration,
    Thresholds,
    outcome_for,
)
from posthog.temporal.cimd_provisioning_review.types import ReviewOutcome

CASES_PATH = Path(__file__).parent / "benchmark_cases.yaml"

ACCEPT_LEGITIMATE_GRID = (0.6, 0.7, 0.8, 0.85, 0.9, 0.95)
ACCEPT_MALICIOUS_GRID = (0.02, 0.05, 0.1, 0.2, 0.3)
REJECT_MALICIOUS_GRID = (0.6, 0.7, 0.8, 0.85, 0.9, 0.95)


class Label(StrEnum):
    LEGITIMATE = "legitimate"
    MALICIOUS = "malicious"


@frozen
class BenchmarkCase:
    name: str
    label: Label
    registration: PartnerRegistration


@frozen
class JudgedCase:
    case: BenchmarkCase
    judgment: PartnerJudgment


@frozen
class ThresholdScore:
    thresholds: Thresholds
    false_accepts: int
    false_rejects: int
    accepted: int
    rejected: int
    escalated: int

    @property
    def safe(self) -> bool:
        return self.false_accepts == 0 and self.false_rejects == 0

    @property
    def settled(self) -> int:
        return self.accepted + self.rejected


def _registration(raw: Mapping[str, Any]) -> PartnerRegistration:
    document = raw.get("document") or {}
    return PartnerRegistration(
        client_id=raw["client_id"],
        domain=raw["domain"],
        client_name=raw["client_name"],
        redirect_uris=tuple(raw.get("redirect_uris", ())),
        logo_uri=raw.get("logo_uri"),
        jwks_uri=raw.get("jwks_uri"),
        requested_scopes=tuple(raw.get("requested_scopes", ())),
        optional_scopes=(),
        client_type=raw.get("client_type", "public"),
        token_endpoint_auth_method=raw.get("token_endpoint_auth_method", "none"),
        partner_tier=raw.get("partner_tier", "public"),
        attested_by_posthog_organization=raw.get("attested_by_posthog_organization"),
        registered_at=None,
        document={
            key: document.get(key) for key in ("client_uri", "tos_uri", "policy_uri", "software_id", "software_version")
        },
        contact_domains=tuple(raw.get("contact_domains", ())),
    )


def load_cases(path: Path = CASES_PATH) -> list[BenchmarkCase]:
    raw_cases = yaml.safe_load(path.read_text()) or []
    return [
        BenchmarkCase(name=raw["name"], label=Label(raw["label"]), registration=_registration(raw)) for raw in raw_cases
    ]


def score(judged: Iterable[JudgedCase], thresholds: Thresholds, *, unsettled: ReviewOutcome) -> ThresholdScore:
    counts = {"false_accepts": 0, "false_rejects": 0, "accepted": 0, "rejected": 0, "escalated": 0}
    for item in judged:
        outcome = outcome_for(item.judgment, thresholds, unsettled=unsettled)
        if outcome == ReviewOutcome.ACCEPT:
            counts["accepted"] += 1
            counts["false_accepts"] += item.case.label == Label.MALICIOUS
        elif outcome == ReviewOutcome.REJECT:
            counts["rejected"] += 1
            counts["false_rejects"] += item.case.label == Label.LEGITIMATE
        else:
            counts["escalated"] += 1
    return ThresholdScore(thresholds=thresholds, **counts)


def sweep(judged: Sequence[JudgedCase], *, unsettled: ReviewOutcome) -> list[ThresholdScore]:
    """Every grid point, best first: safe before unsafe, then most settled, then the strictest
    accept bar, so a tie keeps the margin against cases the benchmark does not have."""
    scores = [
        score(
            judged,
            Thresholds(
                accept_legitimate_at_least=legitimate,
                accept_malicious_at_most=malicious_ceiling,
                reject_malicious_at_least=reject,
            ),
            unsettled=unsettled,
        )
        for legitimate, malicious_ceiling, reject in product(
            ACCEPT_LEGITIMATE_GRID, ACCEPT_MALICIOUS_GRID, REJECT_MALICIOUS_GRID
        )
    ]
    return sorted(
        scores,
        key=lambda item: (
            not item.safe,
            -item.settled,
            -item.thresholds.accept_legitimate_at_least,
            item.thresholds.accept_malicious_at_most,
            -item.thresholds.reject_malicious_at_least,
        ),
    )
