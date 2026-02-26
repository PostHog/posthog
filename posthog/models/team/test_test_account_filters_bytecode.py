from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models.cohort import Cohort


class TestTestAccountFiltersBytecode(BaseTest):
    @parameterized.expand(
        [
            (
                "single_event_filter",
                [
                    {
                        "key": "$host",
                        "operator": "not_regex",
                        "value": r"^(localhost|127\.0\.0\.1)($|:)",
                        "type": "event",
                    }
                ],
            ),
            (
                "single_person_filter",
                [{"key": "email", "operator": "not_icontains", "value": "@example.com", "type": "person"}],
            ),
            (
                "multiple_filters",
                [
                    {
                        "key": "$host",
                        "operator": "not_regex",
                        "value": r"^(localhost|127\.0\.0\.1)($|:)",
                        "type": "event",
                    },
                    {"key": "email", "operator": "not_icontains", "value": "@example.com", "type": "person"},
                ],
            ),
        ]
    )
    def test_compiles_bytecode_on_save(self, _name, filters):
        self.team.test_account_filters = filters
        self.team.save()
        self.team.refresh_from_db()

        assert self.team.test_account_filters_bytecode is not None
        assert isinstance(self.team.test_account_filters_bytecode, list)
        assert len(self.team.test_account_filters_bytecode) > 0
        assert self.team.test_account_filters_bytecode_error is None

    @parameterized.expand(
        [
            ("empty_list", []),
            ("none_via_empty", []),
        ]
    )
    def test_empty_filters_produce_null_bytecode(self, _name, filters):
        self.team.test_account_filters = filters
        self.team.save()
        self.team.refresh_from_db()

        assert self.team.test_account_filters_bytecode is None
        assert self.team.test_account_filters_bytecode_error is None

    def test_cohort_filter_fails_gracefully(self):
        cohort = Cohort.objects.create(team=self.team, name="Test cohort")
        self.team.test_account_filters = [
            {"key": "id", "value": cohort.pk, "type": "cohort"},
        ]
        self.team.save()
        self.team.refresh_from_db()

        assert self.team.test_account_filters_bytecode is None
        assert self.team.test_account_filters_bytecode_error is not None
        assert "cohort" in self.team.test_account_filters_bytecode_error.lower()

    def test_cohort_filter_mixed_with_valid_filters(self):
        cohort = Cohort.objects.create(team=self.team, name="Test cohort")
        self.team.test_account_filters = [
            {"key": "$host", "operator": "not_regex", "value": "localhost", "type": "event"},
            {"key": "id", "value": cohort.pk, "type": "cohort"},
        ]
        self.team.save()
        self.team.refresh_from_db()

        # Even one cohort filter poisons the whole compilation
        assert self.team.test_account_filters_bytecode is None
        assert self.team.test_account_filters_bytecode_error is not None

    def test_error_clears_when_filters_fixed(self):
        cohort = Cohort.objects.create(team=self.team, name="Test cohort")
        self.team.test_account_filters = [
            {"key": "id", "value": cohort.pk, "type": "cohort"},
        ]
        self.team.save()
        assert self.team.test_account_filters_bytecode_error is not None

        self.team.test_account_filters = [
            {"key": "$host", "operator": "not_regex", "value": "localhost", "type": "event"},
        ]
        self.team.save()
        self.team.refresh_from_db()

        assert self.team.test_account_filters_bytecode is not None
        assert self.team.test_account_filters_bytecode_error is None

    def test_bytecode_updates_when_filters_change(self):
        self.team.test_account_filters = [
            {"key": "$host", "operator": "not_regex", "value": "localhost", "type": "event"},
        ]
        self.team.save()
        first_bytecode = self.team.test_account_filters_bytecode
        assert first_bytecode is not None

        self.team.test_account_filters = [
            {"key": "email", "operator": "not_icontains", "value": "@posthog.com", "type": "person"},
        ]
        self.team.save()
        second_bytecode = self.team.test_account_filters_bytecode
        assert second_bytecode is not None
        assert first_bytecode != second_bytecode

    def test_bytecode_included_in_update_fields(self):
        self.team.test_account_filters = [
            {"key": "$host", "operator": "not_regex", "value": "localhost", "type": "event"},
        ]
        self.team.save(update_fields=["test_account_filters"])
        self.team.refresh_from_db()

        assert self.team.test_account_filters_bytecode is not None
        assert self.team.test_account_filters_bytecode_error is None
