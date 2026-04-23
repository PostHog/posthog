"""Tests for summarize_billing.py.

Deterministic: no LLM in the loop, no network, no MCP. Given a canned
response fixture, the script should produce a specific shape.
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

from summarize_billing import load_response, summarize, to_markdown  # noqa: E402

FIXTURES = SCRIPTS_DIR.parent / "fixtures"


@pytest.fixture
def paid() -> dict:
    return load_response(str(FIXTURES / "billing_list_paid_customer.json"))


@pytest.fixture
def free() -> dict:
    return load_response(str(FIXTURES / "billing_list_free_customer.json"))


@pytest.fixture
def near_limit() -> dict:
    return load_response(str(FIXTURES / "billing_list_near_limit.json"))


def test_paid_customer_has_active_subscription(paid: dict) -> None:
    s = summarize(paid)
    assert s["has_active_subscription"] is True
    assert s["subscription_level"] == "paid"


def test_free_customer_has_no_active_subscription(free: dict) -> None:
    s = summarize(free)
    assert s["has_active_subscription"] is False


def test_products_ranked_by_projected_spend(paid: dict) -> None:
    s = summarize(paid)
    projecteds = [p["projected_amount_usd"] for p in s["products_active"]]
    assert all(isinstance(v, Decimal) for v in projecteds)
    assert projecteds == sorted(projecteds, reverse=True)
    assert len(projecteds) >= 2


def test_unsubscribed_products_filtered_out(paid: dict) -> None:
    s = summarize(paid)
    in_summary = {p["type"] for p in s["products_active"]}
    unsubscribed = {p["type"] for p in paid["products"] if not p.get("subscribed")}
    assert in_summary.isdisjoint(unsubscribed)
    assert "data_warehouse" in unsubscribed
    assert "data_warehouse" not in in_summary


def test_free_customer_shows_no_active_products(free: dict) -> None:
    s = summarize(free)
    assert s["products_active"] == []


def test_near_limit_product_is_flagged(near_limit: dict) -> None:
    s = summarize(near_limit)
    near = {p["type"] for p in s["products_near_limit"]}
    assert "product_analytics" in near


def test_addons_on_active_products_are_included(paid: dict) -> None:
    s = summarize(paid)
    pa = next(p for p in s["products_active"] if p["type"] == "product_analytics")
    assert {a["type"] for a in pa["addons"]} == {"group_analytics"}


def test_startup_program_propagates(near_limit: dict) -> None:
    s = summarize(near_limit)
    assert s["startup_program"] == "yc-w24"


def test_custom_limits_passed_through(paid: dict) -> None:
    s = summarize(paid)
    assert s["custom_limits_usd"].get("product_analytics") == 500


def test_markdown_output_under_token_budget(paid: dict) -> None:
    md = to_markdown(summarize(paid))
    assert len(md) < 4000, f"Summary too large: {len(md)} chars"


def test_markdown_output_covers_key_fields(paid: dict) -> None:
    md = to_markdown(summarize(paid))
    assert "Subscription" in md
    assert "Product analytics" in md
    assert "Session replay" in md
    assert "Feature flags" in md
    assert "Group analytics" in md


def test_markdown_free_customer_path(free: dict) -> None:
    md = to_markdown(summarize(free))
    assert "free" in md.lower()
    assert "Active products" in md


def test_markdown_near_limit_surfaces_warning(near_limit: dict) -> None:
    md = to_markdown(summarize(near_limit))
    assert "Near limit" in md
    assert "product_analytics" in md


def test_load_response_handles_mcp_wrapper(tmp_path: Path) -> None:
    inner = {"subscription_level": "paid", "products": []}
    wrapped = [{"type": "text", "text": json.dumps(inner)}]
    path = tmp_path / "wrapped.json"
    path.write_text(json.dumps(wrapped))
    assert load_response(str(path)) == inner


def test_load_response_rejects_non_dict(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(["not", "a", "dict"]))
    with pytest.raises(ValueError):
        load_response(str(path))


def test_projected_totals_are_decimal(paid: dict) -> None:
    s = summarize(paid)
    assert isinstance(s["projected_total_usd"], Decimal)
    assert isinstance(s["current_total_usd"], Decimal)
