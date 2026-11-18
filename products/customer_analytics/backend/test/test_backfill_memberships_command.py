import io
import json

from unittest.mock import AsyncMock, patch

from django.core.management import call_command
from django.test import SimpleTestCase

from parameterized import parameterized

from products.customer_analytics.backend.logic.membership_backfill import MembershipTeam

COMMAND = "products.customer_analytics.backend.management.commands.backfill_memberships"
CONTROL = "products.customer_analytics.backend.logic.membership_backfill_control"


class TestBackfillMembershipsCommand(SimpleTestCase):
    @parameterized.expand(
        [
            (scope, accounts, dry_run)
            for scope, accounts in (
                (["--all-accounts"], ()),
                (["--account", "b", "--account", "a", "--account", "b"], ("a", "b")),
            )
            for dry_run in (False, True)
        ]
    )
    def test_start_preserves_account_scope(
        self, scope: list[str], expected_accounts: tuple[str, ...], dry_run: bool
    ) -> None:
        client = AsyncMock()
        client.start_workflow.return_value.first_execution_run_id = "example-run"
        output = io.StringIO()
        with (
            patch(f"{COMMAND}.Team.objects.filter"),
            patch(f"{COMMAND}.get_membership_group_type_index", return_value=0),
            patch(f"{CONTROL}.async_connect", return_value=client),
        ):
            call_command("backfill_memberships", "start", "--team-id", "17", *scope, dry_run=dry_run, stdout=output)
        assert json.loads(output.getvalue())["run_id"] == "example-run"
        assert client.start_workflow.call_args.args[1] == MembershipTeam(
            team_id=17,
            account_keys=expected_accounts,
            dry_run=dry_run,
        )
