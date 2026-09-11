"""Reviewed adoption of commercial roles from a private manifest.

Export the current role fingerprints, build the manifest outside the repository, preview it, then
apply it. A proposal applies only while its fingerprint still matches, so anything decided in
customer analytics after the review is kept.

    python manage.py adopt_account_ownership --team-id 2 --export-fingerprints > fingerprints.json
    python manage.py adopt_account_ownership --team-id 2 --manifest manifest.json
    python manage.py adopt_account_ownership --team-id 2 --manifest manifest.json --apply

The manifest is JSON: ``{"proposals": [{"account_id", "role", "state": "assigned" | "empty",
"user_id" (assigned only), "expected_fingerprint"}]}``.
"""

import json
from collections import Counter
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.models.team import Team

from products.customer_analytics.backend.logic import ownership_adoption


class Command(BaseCommand):
    help = "Preview or apply reviewed commercial role adoption for one project from a manifest."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--export-fingerprints", action="store_true", help="Print current role fingerprints as JSON.")
        mode.add_argument("--manifest", type=Path, help="Manifest of reviewed proposals to preview or apply.")
        parser.add_argument("--apply", action="store_true", help="Apply the proposals that still hold.")

    def handle(self, *args: Any, **options: Any) -> None:
        if not Team.objects.filter(id=options["team_id"]).exists():
            raise CommandError(f"No team {options['team_id']}")
        if options["export_fingerprints"]:
            self._export(options["team_id"])
            return
        self._review(options["team_id"], options["manifest"], apply=options["apply"])

    def _export(self, team_id: int) -> None:
        rows = [
            {
                "account_id": str(row.account_id),
                "external_id": row.external_id,
                "role": row.role,
                "fingerprint": row.fingerprint,
                "managed": row.managed,
                "holder_user_id": row.holder_user_id,
            }
            for row in ownership_adoption.export_fingerprints(team_id)
        ]
        self.stdout.write(json.dumps({"team_id": team_id, "roles": rows}, indent=2))

    def _review(self, team_id: int, manifest_path: Path, *, apply: bool) -> None:
        try:
            proposals = ownership_adoption.parse_manifest(json.loads(manifest_path.read_text()))
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise CommandError(f"Could not read the manifest: {error}")

        outcomes = ownership_adoption.review(team_id, proposals, apply=apply)
        for outcome in outcomes:
            detail = f" ({outcome.detail})" if outcome.detail else ""
            self.stdout.write(
                f"{outcome.proposal.account_id} {outcome.proposal.role} {outcome.proposal.state}: "
                f"{outcome.disposition}{detail}"
            )
        counts = Counter(outcome.disposition for outcome in outcomes)
        summary = ", ".join(f"{disposition}={count}" for disposition, count in sorted(counts.items()))
        self.stdout.write(f"{'applied' if apply else 'preview'}: {summary or 'no proposals'}")
