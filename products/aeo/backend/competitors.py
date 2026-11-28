"""Whether a brand the answers name is a competitor of the site, decided by Jev.

The catalog suggests every brand that answers to non-branded questions both name and cite. Many of those
are publishers, cloud vendors or tools the site builds on. Jev reads each one next to what the site sells and
says whether a buyer would consider it instead, so the suggestions a person reviews are mostly competitors.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence

from django.conf import settings

import requests

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import ai_gateway_headers, resolve_ai_gateway_config

from products.aeo.backend import decisions
from products.aeo.backend.engines import gateway_post_json
from products.aeo.backend.llm import UnreadableAnswerError, answer_items

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


# Anthropic list prices for the setup model, per million tokens, so the shadow event carries a cost.
_CLAUDE_PRICES_USD: dict[str, tuple[float, float]] = {"claude-sonnet-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50)}
CLAUDE_MAX_TOKENS = 6000
CLAUDE_TIMEOUT_SECONDS = 120

_CLAUDE_INSTRUCTIONS = """A team tracks how AI assistants talk about {domain}. What it does: {description}

Below are companies that the assistants' answers name. For each one, say whether it is a competitor of \
{domain}: a company that sells a product or service a buyer of what {domain} sells would consider instead. \
Publishers, communities, review sites, cloud or tooling vendors the site builds on, partners, integrations and \
unrelated companies are not competitors.

Companies:
{brands}

Answer with only a JSON array, one object per company, with the keys "domain" (string, as given) and \
"competitor" (true or false)."""


class ClaudeConfirmationError(Exception):
    pass


@frozen
class ClaudeConfirmation:
    model: str
    decisions: Mapping[str, bool]
    input_tokens: int
    output_tokens: int
    cost_usd: float | None


def claude_model() -> str:
    return settings.AEO_ANTHROPIC_MODEL


def confirm_competitors_with_claude(
    team_id: int, site: Mapping[str, str], brands: Sequence[BrandInput]
) -> ClaudeConfirmation:
    """The generative model's verdict on every brand in one call, for the shadow comparison. Raises
    ClaudeConfirmationError when the gateway is not configured, the call fails or the answer is unreadable."""
    gateway = resolve_ai_gateway_config()
    if gateway is None:
        raise ClaudeConfirmationError("AI gateway is not configured")
    instructions = _CLAUDE_INSTRUCTIONS.format(
        domain=site.get("site", ""),
        description=site.get("description", "unknown"),
        brands="\n".join(f"- {b.name} ({b.domain})" for b in brands),
    )
    headers = {
        "Authorization": f"Bearer {gateway.api_key}",
        "anthropic-version": "2023-06-01",
        **(
            ai_gateway_headers(
                trace_id=str(uuid.uuid4()), properties={"team_id": str(team_id), "aeo_feature": f"{FEATURE}_shadow"}
            )
            or {}
        ),
    }
    model = claude_model()
    try:
        with requests.Session() as session:
            session.trust_env = False
            body = gateway_post_json(
                session,
                gateway.url.rstrip("/") + "/messages",
                headers,
                {
                    "model": model,
                    "max_tokens": CLAUDE_MAX_TOKENS,
                    "messages": [{"role": "user", "content": instructions}],
                },
                timeout=CLAUDE_TIMEOUT_SECONDS,
            )
    except requests.RequestException as error:
        raise ClaudeConfirmationError(type(error).__name__) from error
    text = "".join(block.get("text", "") for block in body.get("content") or [] if block.get("type") == "text")
    try:
        items = answer_items(text)
    except UnreadableAnswerError as error:
        raise ClaudeConfirmationError("unreadable answer") from error
    said = {str(item.get("domain")): item.get("competitor") is True for item in items if isinstance(item, dict)}
    usage = body.get("usage") or {}
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    prices = _CLAUDE_PRICES_USD.get(model)
    cost = (input_tokens * prices[0] + output_tokens * prices[1]) / 1e6 if prices else None
    return ClaudeConfirmation(
        model=model,
        decisions={b.domain: said.get(b.domain, False) for b in brands},
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
    )
