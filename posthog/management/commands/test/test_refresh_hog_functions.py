import json
from io import StringIO

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command

from posthog.cdp.filters import RUNTIME_CONTRACT
from posthog.cdp.validation import generate_template_bytecode
from posthog.models import Team

from products.cdp.backend.models.hog_functions.hog_function import HogFunction


class TestRefreshHogFunctions(BaseTest):
    def setUp(self):
        super().setUp()

        # Create additional teams for testing
        self.team2 = Team.objects.create(organization=self.organization, name="Test Team 2")

        # Create HogFunctions for testing
        with patch("products.cdp.backend.models.hog_functions.hog_function.reload_hog_functions_on_workers"):
            self.hog_function1 = HogFunction.objects.create(
                team=self.team,
                name="Test Function 1",
                type="destination",
                description="Test Description 1",
                hog="return event",
                enabled=True,
            )

            self.hog_function2 = HogFunction.objects.create(
                team=self.team,
                name="Test Function 2",
                type="transformation",
                description="Test Description 2",
                hog="return event",
                enabled=True,
            )

            self.hog_function3 = HogFunction.objects.create(
                team=self.team2,
                name="Test Function 3",
                type="destination",
                description="Test Description 3",
                hog="return event",
                enabled=True,
            )

            # Create disabled function - should also be processed
            self.disabled_function = HogFunction.objects.create(
                team=self.team,
                name="Disabled Function",
                type="destination",
                enabled=False,
            )

            # Create deleted function - should not be processed
            self.deleted_function = HogFunction.objects.create(
                team=self.team,
                name="Deleted Function",
                type="destination",
                enabled=True,
                deleted=True,
            )

    @patch("products.cdp.backend.models.hog_functions.hog_function.reload_hog_functions_on_workers")
    def test_refresh_all_hog_functions(self, mock_reload):
        """Test refreshing all non-deleted destination HogFunctions (both enabled and disabled) across all teams."""

        out = StringIO()
        call_command("refresh_hog_functions", stdout=out)

        # Should have refreshed 3 destination functions
        # (hog_function1, hog_function3, disabled_function)
        # The transformation hog_function2 and deleted_function should be excluded
        assert mock_reload.call_count == 3

        output = out.getvalue()
        self.assertIn("Found 3 HogFunctions to process", output)
        self.assertIn("Processed: 3", output)
        self.assertIn("Updated: 3", output)
        self.assertIn("Errors: 0", output)

    @patch("products.cdp.backend.models.hog_functions.hog_function.reload_hog_functions_on_workers")
    def test_refresh_by_team_id(self, mock_reload):
        """Test refreshing destination HogFunctions for a specific team."""

        out = StringIO()
        call_command("refresh_hog_functions", team_id=self.team.id, stdout=out)

        # Should have refreshed destination functions from team1 (hog_function1, disabled_function)
        # The transformation hog_function2 and deleted_function should be excluded
        assert mock_reload.call_count == 2

        output = out.getvalue()
        self.assertIn(f"Processing HogFunctions for team: {self.team.id}", output)
        self.assertIn("Found 2 HogFunctions to process", output)
        self.assertIn("Updated: 2", output)

    @patch("products.cdp.backend.models.hog_functions.hog_function.reload_hog_functions_on_workers")
    def test_refresh_by_hog_function_id(self, mock_reload):
        """Test refreshing a specific HogFunction by ID."""

        out = StringIO()
        call_command("refresh_hog_functions", hog_function_id=str(self.hog_function1.id), stdout=out)

        # Should have refreshed only the specific function
        assert mock_reload.call_count == 1

        output = out.getvalue()
        self.assertIn(f"Processing single HogFunction: {self.hog_function1.id}", output)
        self.assertIn("Found 1 HogFunctions to process", output)
        self.assertIn("Updated: 1", output)

    @patch("products.cdp.backend.models.hog_functions.hog_function.reload_hog_functions_on_workers")
    def test_nonexistent_team_id(self, mock_reload):
        """Test handling of nonexistent team ID."""

        out = StringIO()
        call_command("refresh_hog_functions", team_id=99999, stdout=out)

        assert mock_reload.call_count == 0

        output = out.getvalue()
        self.assertIn("Found 0 HogFunctions to process", output)
        self.assertIn("No HogFunctions found matching criteria", output)

    @patch("products.cdp.backend.models.hog_functions.hog_function.reload_hog_functions_on_workers")
    def test_nonexistent_hog_function_id(self, mock_reload):
        """Test handling of nonexistent HogFunction ID."""

        out = StringIO()
        # Use a valid UUID format that doesn't exist
        nonexistent_uuid = "00000000-0000-0000-0000-000000000000"
        call_command("refresh_hog_functions", hog_function_id=nonexistent_uuid, stdout=out)

        assert mock_reload.call_count == 0

        output = out.getvalue()
        self.assertIn("Found 0 HogFunctions to process", output)
        self.assertIn("No HogFunctions found matching criteria", output)

    def _unstamped(self, inputs: dict, inputs_schema: list, encrypted_inputs: dict | None = None) -> HogFunction:
        """A destination as it was saved before stamping existed: bytecode everywhere, no stamp anywhere."""
        with patch("products.cdp.backend.models.hog_functions.hog_function.reload_hog_functions_on_workers"):
            fn = HogFunction.objects.create(
                team=self.team,
                name="Saved before stamping",
                type="destination",
                hog="return event",
                enabled=True,
                inputs_schema=inputs_schema,
                inputs=inputs,
                encrypted_inputs=encrypted_inputs,
                filters={"events": [{"id": "$pageview", "type": "events"}]},
            )
        # The model save stamps the filters. Strip it so the fixture is honestly pre-stamping.
        filters = {key: value for key, value in fn.filters.items() if key != "bytecode_contract"}
        HogFunction.objects.filter(pk=fn.pk).update(filters=filters)
        return HogFunction.objects.get(pk=fn.pk)

    @patch("products.cdp.backend.models.hog_functions.hog_function.reload_hog_functions_on_workers")
    def test_stamps_filters_and_every_hog_input_of_an_unstamped_destination(self, mock_reload):
        template = json.loads(json.dumps(generate_template_bytecode("{event.uuid}", set())))
        fn = self._unstamped(
            inputs={
                "url": {"value": "{event.uuid}", "bytecode": template},
                "body": {"value": {"id": "{event.uuid}"}, "bytecode": {"id": template}},
                "note": {"value": "{{ event.uuid }}", "templating": "liquid"},
                "method": {"value": "POST"},
            },
            inputs_schema=[
                {"key": "url", "type": "string"},
                {"key": "body", "type": "json"},
                {"key": "note", "type": "string"},
                {"key": "method", "type": "string"},
                {"key": "token", "type": "string", "secret": True},
            ],
            encrypted_inputs={"token": {"value": "{event.uuid}", "bytecode": template}},
        )
        assert "bytecode_contract" not in fn.filters
        assert "bytecode_contract" not in fn.inputs["url"]

        out = StringIO()
        call_command("refresh_hog_functions", hog_function_id=str(fn.id), stdout=out)

        fn.refresh_from_db()
        assert fn.filters["bytecode_contract"] == RUNTIME_CONTRACT
        assert fn.inputs["url"] == {
            "value": "{event.uuid}",
            "bytecode": template,
            "bytecode_contract": RUNTIME_CONTRACT,
        }
        assert fn.inputs["body"]["bytecode_contract"] == RUNTIME_CONTRACT
        assert fn.inputs["body"]["bytecode"] == {"id": template}
        # Secret templates are compiled the same way, and the value never leaves the process.
        assert fn.encrypted_inputs["token"]["bytecode_contract"] == RUNTIME_CONTRACT
        # Liquid has no bytecode and a plain value compiles to nothing that could drift.
        assert fn.inputs["note"] == {"value": "{{ event.uuid }}", "templating": "liquid"}
        assert fn.inputs["method"] == {"value": "POST"}
        assert "Inputs stamped: 3" in out.getvalue()
        assert mock_reload.call_count == 1

    @patch("products.cdp.backend.models.hog_functions.hog_function.reload_hog_functions_on_workers")
    def test_keeps_an_input_that_no_longer_compiles_and_leaves_it_unstamped(self, mock_reload):
        # A template that today's guard refuses keeps running on its old bytecode. It must not get a
        # stamp, or the runtime would read its failures as our change rather than the owner's.
        stale = ["_H", 1, 32, "thing", 32, "nosuch", 1, 2]
        good = json.loads(json.dumps(generate_template_bytecode("{event.uuid}", set())))
        fn = self._unstamped(
            inputs={
                "url": {"value": "{event.uuid}", "bytecode": good},
                "bad": {"value": "{nosuch.thing}", "bytecode": stale},
            },
            inputs_schema=[{"key": "url", "type": "string"}, {"key": "bad", "type": "string"}],
        )

        out = StringIO()
        call_command("refresh_hog_functions", hog_function_id=str(fn.id), stdout=out)

        fn.refresh_from_db()
        assert fn.inputs["url"]["bytecode_contract"] == RUNTIME_CONTRACT
        assert fn.inputs["bad"] == {"value": "{nosuch.thing}", "bytecode": stale}
        assert fn.filters["bytecode_contract"] == RUNTIME_CONTRACT
        assert "Inputs stamped: 1" in out.getvalue()
        assert "Inputs skipped: 1" in out.getvalue()

    @patch("products.cdp.backend.models.hog_functions.hog_function.reload_hog_functions_on_workers")
    def test_dry_run_reports_and_writes_nothing(self, mock_reload):
        template = json.loads(json.dumps(generate_template_bytecode("{event.uuid}", set())))
        fn = self._unstamped(
            inputs={"url": {"value": "{event.uuid}", "bytecode": template}},
            inputs_schema=[{"key": "url", "type": "string"}],
        )

        out = StringIO()
        call_command("refresh_hog_functions", hog_function_id=str(fn.id), dry_run=True, stdout=out)

        fn.refresh_from_db()
        assert "bytecode_contract" not in fn.filters
        assert "bytecode_contract" not in fn.inputs["url"]
        assert mock_reload.call_count == 0
        assert "Inputs stamped: 1" in out.getvalue()
        assert "Dry run" in out.getvalue()
