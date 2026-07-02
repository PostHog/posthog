from posthog.test.base import BaseTest

from django.utils import timezone

from parameterized import parameterized

from products.cohorts.backend.models.cohort import Cohort


def _person_filters(email: str) -> dict:
    return {
        "properties": {
            "type": "OR",
            "values": [{"type": "OR", "values": [{"key": "email", "value": email, "type": "person"}]}],
        }
    }


FILTERS_A = _person_filters("a@a.com")
FILTERS_B = _person_filters("b@b.com")
FILTERS_C = _person_filters("c@c.com")


class TestCohortDefinitionVersion(BaseTest):
    def _create_cohort(self) -> Cohort:
        return Cohort.objects.create(team=self.team, name="cohort", filters=FILTERS_A)

    @parameterized.expand(
        [
            ("filters", "filters", FILTERS_B),
            ("query", "query", {"kind": "ActorsQuery", "select": ["id"]}),
            ("groups", "groups", [{"properties": [{"key": "email", "value": "x", "type": "person"}]}]),
            ("is_static", "is_static", True),
        ]
    )
    def test_definition_field_change_bumps_version(self, _name: str, field: str, new_value):
        cohort = self._create_cohort()
        initial = cohort.definition_version

        setattr(cohort, field, new_value)
        cohort.save()

        cohort.refresh_from_db()
        assert cohort.definition_version == initial + 1

    @parameterized.expand(
        [
            ("non_definition_full_save", {"name": "renamed"}, None),
            (
                "recalc_bookkeeping_update_fields",
                {"is_calculating": True, "count": 42},
                ["is_calculating", "count"],
            ),
            (
                # Mirrors the finally-save in calculate_people_ch, which lists groups and
                # cohort_type in update_fields without changing their values.
                "calculation_completion_save",
                {"last_calculation": timezone.now(), "errors_calculating": 0},
                ["last_calculation", "errors_calculating", "last_error_at", "cohort_type", "groups"],
            ),
            (
                # A definition field changed in memory but excluded from update_fields is
                # not persisted, so it must not bump the version either.
                "update_fields_ignores_unpersisted_definition_changes",
                {"filters": FILTERS_B},
                ["groups"],
            ),
            ("unchanged_definition_full_save", {}, None),
        ]
    )
    def test_non_definition_saves_do_not_bump(self, _name: str, attrs: dict, update_fields):
        cohort = self._create_cohort()
        initial = cohort.definition_version

        for field, value in attrs.items():
            setattr(cohort, field, value)
        if update_fields is None:
            cohort.save()
        else:
            cohort.save(update_fields=update_fields)

        cohort.refresh_from_db()
        assert cohort.definition_version == initial

    def test_bump_persists_when_saving_with_update_fields(self):
        cohort = self._create_cohort()
        initial = cohort.definition_version

        cohort.filters = FILTERS_B
        cohort.save(update_fields=["filters"])

        cohort.refresh_from_db()
        assert cohort.filters == FILTERS_B
        assert cohort.definition_version == initial + 1

    def test_bump_reads_version_from_db_not_stale_instance(self):
        cohort = self._create_cohort()
        initial = cohort.definition_version
        stale_copy = Cohort.objects.get(pk=cohort.pk)

        cohort.filters = FILTERS_B
        cohort.save()
        stale_copy.filters = FILTERS_C
        stale_copy.save()

        stale_copy.refresh_from_db()
        assert stale_copy.definition_version == initial + 2
