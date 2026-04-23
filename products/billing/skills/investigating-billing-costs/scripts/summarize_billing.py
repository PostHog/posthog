"""Summarize a billing-list response into a compact, agent-friendly markdown report.

The `posthog:billing-list` MCP tool returns ~15-20 KB of JSON even with
`response.exclude` applied. Agents only need a fraction of that to answer
cost/usage questions. This script reads the stashed response and emits either:

- A markdown summary (default) - ~500 tokens, suitable for pasting into context
- Structured JSON (`--json`) - for programmatic chaining with other scripts

Usage:
    python3 scripts/summarize_billing.py <path-to-billing-list-response.json>
    python3 scripts/summarize_billing.py <path> --json

Input file can be either the raw billing-list JSON, or the Claude Code
tool-result wrapper (list of {"type": "text", "text": "<json>"}).
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal, InvalidOperation


def load_response(path: str) -> dict:
    """Load a billing-list response, handling the MCP tool-result wrapper."""
    with open(path) as f:
        raw = json.load(f)
    if isinstance(raw, list) and raw and isinstance(raw[0], dict) and raw[0].get("type") == "text":
        raw = json.loads(raw[0]["text"])
    if not isinstance(raw, dict):
        raise ValueError(f"Expected billing-list response to be a dict, got {type(raw).__name__}")
    return raw


def _to_decimal(value) -> Decimal:
    """Coerce billing API monetary fields (typically returned as strings) to Decimal.

    Using Decimal rather than float matches the billing backend's internal
    representation and avoids float precision artifacts (e.g. 0.1 + 0.2 drift).
    """
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _pct_of_limit(product: dict) -> float | None:
    current = product.get("current_usage") or 0
    limit = product.get("usage_limit")
    if not limit:
        return None
    return round(100 * current / limit, 1)


def _addon_summaries(product: dict) -> list[dict]:
    addons = []
    for a in product.get("addons") or []:
        if not a.get("subscribed"):
            continue
        addons.append(
            {
                "type": a.get("type"),
                "name": a.get("name"),
                "current_amount_usd": _to_decimal(a.get("current_amount_usd")),
                "projected_amount_usd": _to_decimal(a.get("projected_amount_usd")),
            }
        )
    return addons


def summarize(billing: dict) -> dict:
    """Extract the decision-relevant slice of a billing-list response."""
    period = billing.get("billing_period") or {}

    products_active: list[dict] = []
    products_near_limit: list[dict] = []

    for p in billing.get("products") or []:
        if not p.get("subscribed"):
            continue
        current = p.get("current_usage") or 0
        projected_usd = _to_decimal(p.get("projected_amount_usd"))
        current_usd = _to_decimal(p.get("current_amount_usd"))

        if current == 0 and projected_usd == Decimal("0") and current_usd == Decimal("0"):
            continue

        pct = _pct_of_limit(p)
        product_summary = {
            "type": p.get("type"),
            "name": p.get("name"),
            "current_usage": current,
            "limit": p.get("usage_limit"),
            "pct_of_limit": pct,
            "current_amount_usd": current_usd,
            "projected_amount_usd": projected_usd,
            "addons": _addon_summaries(p),
        }
        products_active.append(product_summary)

        if pct is not None and pct >= 80:
            products_near_limit.append({"type": p.get("type"), "pct": pct})

    products_active.sort(key=lambda x: x["projected_amount_usd"], reverse=True)

    return {
        "subscription_level": billing.get("subscription_level"),
        "has_active_subscription": billing.get("has_active_subscription"),
        "billing_plan": billing.get("billing_plan"),
        "period_start": period.get("current_period_start"),
        "period_end": period.get("current_period_end"),
        "period_interval": period.get("interval"),
        "current_total_usd": _to_decimal(billing.get("current_total_amount_usd")),
        "projected_total_usd": _to_decimal(billing.get("projected_total_amount_usd")),
        "projected_total_with_limit_usd": _to_decimal(billing.get("projected_total_amount_usd_with_limit")),
        "discount_percent": billing.get("discount_percent"),
        "startup_program": billing.get("startup_program_label"),
        "free_trial_until": billing.get("free_trial_until"),
        "custom_limits_usd": billing.get("custom_limits_usd") or {},
        "products_active": products_active,
        "products_near_limit": products_near_limit,
    }


def _fmt_usd(value) -> str:
    if isinstance(value, Decimal):
        return f"${value:.2f}"
    if isinstance(value, (int, float)):
        return f"${value:.2f}"
    return "-"


def _fmt_int(value) -> str:
    return f"{value:,}" if isinstance(value, (int, float)) else "-"


def to_markdown(s: dict) -> str:
    lines = []

    sub_level = s.get("subscription_level") or "unknown"
    period_end = s.get("period_end") or "?"
    projected = _fmt_usd(s.get("projected_total_usd"))
    current = _fmt_usd(s.get("current_total_usd"))

    if not s.get("has_active_subscription"):
        lines.append(f"**Subscription:** free ({sub_level}). Period ends {period_end}.")
    else:
        lines.append(
            f"**Subscription:** {sub_level} "
            f"(plan `{s.get('billing_plan') or '-'}`). "
            f"Period {s.get('period_start') or '?'} -> {period_end}. "
            f"Current {current}, projected {projected}."
        )

    if s.get("startup_program"):
        lines.append(f"**Startup program:** `{s['startup_program']}` "
                     "(spend does not fully reflect usage).")

    if s.get("free_trial_until"):
        lines.append(f"**Trial until:** {s['free_trial_until']}")

    discount = s.get("discount_percent")
    if discount:
        lines.append(f"**Discount:** {discount}%")

    if s.get("products_active"):
        lines.append("")
        lines.append("**Active products** (subscribed + has usage or projected spend, "
                     "sorted by projected spend):")
        lines.append("")
        lines.append("| Product | Current usage | Limit | % of limit | Current $ | Projected $ |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for p in s["products_active"]:
            limit = _fmt_int(p["limit"]) if p["limit"] is not None else "-"
            pct = f"{p['pct_of_limit']}%" if p["pct_of_limit"] is not None else "-"
            lines.append(
                f"| {p['name']} "
                f"| {_fmt_int(p['current_usage'])} "
                f"| {limit} "
                f"| {pct} "
                f"| {_fmt_usd(p['current_amount_usd'])} "
                f"| {_fmt_usd(p['projected_amount_usd'])} |"
            )
    else:
        lines.append("")
        lines.append("**Active products:** none with usage or projected spend yet.")

    addon_lines: list[str] = []
    for p in s.get("products_active") or []:
        for a in p.get("addons") or []:
            addon_lines.append(
                f"- {p['name']} / {a['name']}: "
                f"{_fmt_usd(a['current_amount_usd'])} current, "
                f"{_fmt_usd(a['projected_amount_usd'])} projected"
            )
    if addon_lines:
        lines.append("")
        lines.append("**Active addons:**")
        lines.extend(addon_lines)

    if s.get("products_near_limit"):
        lines.append("")
        lines.append("**Near limit (>=80%):**")
        for n in s["products_near_limit"]:
            lines.append(f"- {n['type']}: {n['pct']}%")

    custom = s.get("custom_limits_usd") or {}
    non_null = {k: v for k, v in custom.items() if v is not None}
    if non_null:
        parts = ", ".join(f"{k}=${v}" for k, v in non_null.items())
        lines.append("")
        lines.append(f"**Custom spend limits:** {parts}")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", help="Path to the stashed billing-list response JSON")
    parser.add_argument("--json", action="store_true", help="Emit structured JSON instead of markdown")
    args = parser.parse_args(argv)

    data = load_response(args.path)
    summary = summarize(data)

    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        print(to_markdown(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
