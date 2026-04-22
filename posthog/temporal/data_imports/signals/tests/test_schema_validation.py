import json
import dataclasses
from pathlib import Path
from typing import get_args

import pytest

from posthog.schema import SignalInput

from posthog.temporal.data_imports.signals.conversations_tickets import conversations_ticket_emitter
from posthog.temporal.data_imports.signals.github_issues import github_issue_emitter
from posthog.temporal.data_imports.signals.linear_issues import linear_issue_emitter
from posthog.temporal.data_imports.signals.zendesk_tickets import zendesk_ticket_emitter

FIXTURES_DIR = Path(__file__).resolve().parents[5] / "products" / "signals" / "eval" / "fixtures"


def _load_fixture(filename: str) -> list[dict]:
    with open(FIXTURES_DIR / filename) as f:
        return json.load(f)


def _validate_output(output):
    data = dataclasses.asdict(output)
    for variant_type in get_args(SignalInput.model_fields["root"].annotation):
        fields = variant_type.model_fields
        if (
            fields["source_product"].default == output.source_product
            and fields["source_type"].default == output.source_type
        ):
            variant_type.model_validate(data)
            return
    raise ValueError(f"No SignalInput variant for ({output.source_product}, {output.source_type})")


GITHUB_RECORDS = _load_fixture("github_issues.json")
ZENDESK_RECORDS = _load_fixture("zendesk_tickets.json")
LINEAR_RECORDS = _load_fixture("linear_issues.json")
CONVERSATIONS_RECORDS = _load_fixture("conversations_tickets.json")


class TestGithubFixtureSchemaValidation:
    @pytest.mark.parametrize(
        "record",
        GITHUB_RECORDS,
        ids=[r.get("html_url", r["id"]) for r in GITHUB_RECORDS],
    )
    def test_emitter_output_matches_schema(self, record):
        output = github_issue_emitter(team_id=1, record=record)
        if output is not None:
            _validate_output(output)


class TestZendeskFixtureSchemaValidation:
    @pytest.mark.parametrize(
        "record",
        ZENDESK_RECORDS,
        ids=[r["id"] for r in ZENDESK_RECORDS],
    )
    def test_emitter_output_matches_schema(self, record):
        output = zendesk_ticket_emitter(team_id=1, record=record)
        if output is not None:
            _validate_output(output)


class TestLinearFixtureSchemaValidation:
    @pytest.mark.parametrize(
        "record",
        LINEAR_RECORDS,
        ids=[r.get("identifier", r["id"]) for r in LINEAR_RECORDS],
    )
    def test_emitter_output_matches_schema(self, record):
        output = linear_issue_emitter(team_id=1, record=record)
        if output is not None:
            _validate_output(output)


class TestConversationsFixtureSchemaValidation:
    @pytest.mark.parametrize(
        "record",
        CONVERSATIONS_RECORDS,
        ids=[r["id"] for r in CONVERSATIONS_RECORDS],
    )
    def test_emitter_output_matches_schema(self, record):
        output = conversations_ticket_emitter(team_id=1, record=record)
        if output is not None:
            _validate_output(output)
