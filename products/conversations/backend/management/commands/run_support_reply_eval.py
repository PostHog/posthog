"""Run the support-reply eval fixtures through the pipeline.

Mocked by default (no sandbox, no LLM). Pass --live to run the real draft agent.
CI uses the mocked variant.
"""

from __future__ import annotations

import asyncio
from functools import partial
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from products.conversations.evals.fixtures import FIXTURES, SupportReplyFixture, expected_for
from products.conversations.evals.report import format_report
from products.conversations.evals.runner import run_fixture
from products.conversations.evals.scorers import DETERMINISTIC_SCORERS
from products.conversations.evals.seeders import provision_eval_team, seed_case, teardown_eval_team


class Command(BaseCommand):
    help = "Run support-reply eval fixtures. Mocked by default; pass --live for the real draft agent."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--live", action="store_true", help="Run the real sandbox draft instead of the stub.")
        parser.add_argument("--fixture", type=str, default="", help="Substring filter on fixture name.")
        parser.add_argument("--keep", action="store_true", help="Leave the ephemeral eval team in the database.")

    def handle(self, *args, **options) -> None:
        live: bool = options["live"]
        fixture_filter: str = options["fixture"]
        keep: bool = options["keep"]
        rows = asyncio.run(self._run(live=live, fixture_filter=fixture_filter, keep=keep))
        self.stdout.write(format_report(rows))
        if any(output.get("exit_code") not in (0, None) for _, output, _ in rows):
            raise CommandError("One or more support-reply fixtures failed to execute.")

    async def _run(
        self, *, live: bool, fixture_filter: str, keep: bool
    ) -> list[tuple[SupportReplyFixture, dict[str, Any], dict[str, Any]]]:
        selected = [f for f in FIXTURES if not fixture_filter or fixture_filter in f.name]
        rows: list[tuple[SupportReplyFixture, dict[str, Any], dict[str, Any]]] = []
        for fixture in selected:
            organization, team, user = await asyncio.to_thread(partial(provision_eval_team, label=fixture.name))
            try:
                seed = await asyncio.to_thread(partial(seed_case, team=team, user=user, fixture=fixture))
                output = await run_fixture(fixture, seed, live=live)
                expected = expected_for(fixture)
                scores = {scorer._name(): scorer._run_eval_sync(output, expected) for scorer in DETERMINISTIC_SCORERS}
                rows.append((fixture, output, scores))
            finally:
                if not keep:
                    await asyncio.to_thread(partial(teardown_eval_team, organization=organization, user=user))
        return rows
