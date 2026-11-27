"""Whether a brand the answers name is a competitor of the site, decided by Jev.

The catalog suggests every brand that answers to non-branded questions both name and cite. Many of those
are publishers, cloud vendors or tools the site builds on. Jev reads each one next to what the site sells and
says whether a buyer would consider it instead, so the suggestions a person reviews are mostly competitors.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from posthog.dataclasses import frozen

from products.aeo.backend import decisions

# The model says yes at 0.5 to most brands named after a common word (if.ee, tool.news). On the labelled
# posthog.com set, 0.7 trades a tenth of recall for a third more precision; see eval/report.md.
COMPETITOR_PROBABILITY = 0.7
FEATURE = "competitor_confirmation"

_QUESTION = (
    "Is the company `{key}` a competitor of `site`: does it sell a product or service that a buyer of what "
    "`site` sells would consider instead of `site`?"
)
_TRUE = "Sells a product or service in the same category, to the same kind of buyer, for the same need."
_FALSE = (
    "A publisher, blog, community, marketplace, review or comparison site, a cloud, infrastructure or tooling "
    "vendor the site builds on, a partner or integration, a customer, or an unrelated company."
)


@frozen
class BrandInput:
    name: str
    domain: str


@frozen
class CompetitorVerdict:
    brand: BrandInput
    probability: float

    @property
    def is_competitor(self) -> bool:
        return self.probability >= COMPETITOR_PROBABILITY


def site_context(*, domain: str, brand: str = "", description: str = "") -> Mapping[str, str]:
    return {"site": domain[:200], "brand": brand[:200] or "unknown", "description": description[:1000] or "unknown"}


def confirm_competitors(
    team_id: int,
    site: Mapping[str, str],
    brands: Sequence[BrandInput],
    *,
    usage: list[decisions.DecisionUsage] | None = None,
) -> list[CompetitorVerdict]:
    """One verdict per brand, in the brands' order. Raises `decisions.DecisionError` when the model gives no
    usable answer."""
    if not brands:
        return []
    probabilities = decisions.yes_probabilities(
        team_id=team_id,
        feature=FEATURE,
        context=dict(site),
        items=[f"{brand.name} ({brand.domain})" for brand in brands],
        item_key="brands",
        question=_QUESTION,
        criteria_true=_TRUE,
        criteria_false=_FALSE,
        usage=usage,
    )
    return [CompetitorVerdict(brand=brand, probability=p) for brand, p in zip(brands, probabilities)]
