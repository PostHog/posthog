from io import StringIO

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError

from products.cdp.backend.models.hog_functions.hog_function import HogFunction, HogFunctionType

TASK = "posthog.management.commands.notify_uncompilable_hog_function_filters.send_hog_function_filters_uncompilable"


class TestNotifyUncompilableHogFunctionFilters(BaseTest):
    def _broken(
        self, name: str = "Broken", enabled: bool = True, type: str = HogFunctionType.DESTINATION
    ) -> HogFunction:
        hog_function = HogFunction.objects.create(team=self.team, name=name, enabled=enabled, type=type)
        # Past save(), which recompiles the filters and clears the error. This is the shape the row
        # has in the database.
        HogFunction.objects.filter(id=hog_function.id).update(
            filters={"bytecode": None, "bytecode_error": "Cohort membership can't be evaluated"}
        )
        return hog_function

    def test_dry_run_reports_without_emailing_or_disabling(self) -> None:
        hog_function = self._broken()
        out = StringIO()

        with patch(TASK) as task:
            call_command("notify_uncompilable_hog_function_filters", stdout=out)

        task.delay.assert_not_called()
        hog_function.refresh_from_db()
        assert hog_function.enabled is True
        assert str(hog_function.id) in out.getvalue()
        assert "Dry run" in out.getvalue()

    def test_apply_emails_each_function_and_leaves_it_enabled(self) -> None:
        hog_function = self._broken()

        with patch(TASK) as task:
            call_command("notify_uncompilable_hog_function_filters", "--apply", stdout=StringIO())

        task.delay.assert_called_once_with(str(hog_function.id))
        hog_function.refresh_from_db()
        assert hog_function.enabled is True

    def test_disable_turns_the_function_off(self) -> None:
        hog_function = self._broken()

        with patch(TASK) as task:
            call_command("notify_uncompilable_hog_function_filters", "--apply", "--disable", stdout=StringIO())

        task.delay.assert_called_once_with(str(hog_function.id))
        hog_function.refresh_from_db()
        assert hog_function.enabled is False

    def test_leaves_every_type_other_than_a_destination_alone(self) -> None:
        # Transformations, source webhooks and internal destinations compile bytecode too and carry
        # the same error, but the email names a destination and links to the destinations page.
        for hog_type in (
            HogFunctionType.TRANSFORMATION,
            HogFunctionType.SOURCE_WEBHOOK,
            HogFunctionType.INTERNAL_DESTINATION,
        ):
            self._broken(name=f"Broken {hog_type}", type=hog_type)
        out = StringIO()

        with patch(TASK) as task:
            call_command("notify_uncompilable_hog_function_filters", "--apply", stdout=out)

        task.delay.assert_not_called()
        assert "0 enabled function(s)" in out.getvalue()

    def test_rejects_a_limit_below_one(self) -> None:
        # `if limit:` read 0 as "no limit" and would hand the whole fleet to --apply.
        self._broken()

        with patch(TASK) as task, self.assertRaises(CommandError):
            call_command("notify_uncompilable_hog_function_filters", "--apply", "--limit", "0", stdout=StringIO())

        task.delay.assert_not_called()

    def test_skips_functions_that_compile_and_functions_already_off(self) -> None:
        HogFunction.objects.create(team=self.team, name="Healthy", enabled=True)
        self._broken(name="Already off", enabled=False)
        out = StringIO()

        with patch(TASK) as task:
            call_command("notify_uncompilable_hog_function_filters", "--apply", stdout=out)

        task.delay.assert_not_called()
        assert "0 enabled function(s)" in out.getvalue()
