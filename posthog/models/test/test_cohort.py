from posthog.test.base import BaseTest

from posthog.models.cohort.cohort import Cohort


class TestCohort(BaseTest):
    def test_cohort_creation(self):
        cohort = Cohort.objects.create(name="Test Cohort", team=self.team)
        self.assertEqual(cohort.name, "Test Cohort")


class TestCohortDependency(BaseTest):
    def _create_cohort(self, name: str, **kwargs):
        return Cohort.objects.create(name=name, team=self.team, **kwargs)

    def _assert_depends_on(self, dependent_cohort, referenced_cohort):
        self.assertEqual(list(dependent_cohort.dependent_cohorts), [referenced_cohort])
        self.assertEqual(list(referenced_cohort.referencing_cohorts), [dependent_cohort])

    def _assert_cohorts_have_no_relationships(self, *cohorts):
        for cohort in cohorts:
            self.assertEqual(len(cohort.referencing_cohorts), 0, f"Expected no referencing cohorts for {cohort.name}")
            self.assertEqual(len(cohort.dependent_cohorts), 0, f"Expected no dependent cohorts for {cohort.name}")

    # Filters
    # -------

    def test_cohort_filter_dependency_created(self):
        """
        When a new cohort is created including a filter that references another cohort,
        a dependency should be created.
        """
        cohort_a = self._create_cohort(name="Test Cohort A")
        cohort_b = self._create_cohort(
            name="Test Cohort B", filters={"properties": {"values": [{"type": "cohort", "value": cohort_a.id}]}}
        )

        self._assert_depends_on(cohort_b, cohort_a)

    def test_cohort_filter_dependency_updated(self):
        """
        When a cohort's filters are updated to add a dependency, the dependency should be created.
        """
        cohort_a = self._create_cohort(name="Test Cohort A")
        cohort_b = self._create_cohort(name="Test Cohort B")

        self._assert_cohorts_have_no_relationships(cohort_a, cohort_b)

        cohort_b.groups = ([{"properties": [{"type": "cohort", "value": cohort_a.id}]}],)
        cohort_b.save()

        self._assert_depends_on(cohort_b, cohort_a)

    def test_cohort_filter_dependency_updated_delete(self):
        """
        When a cohort's filters are updated to remove a dependency, the dependency should be removed.
        """
        cohort_a = self._create_cohort(name="Test Cohort A")
        cohort_b = self._create_cohort(
            name="Test Cohort B", filters={"properties": {"values": [{"type": "cohort", "value": cohort_a.id}]}}
        )

        self._assert_depends_on(cohort_b, cohort_a)

        cohort_b.filters = {"properties": {}}
        cohort_b.save()

        self._assert_cohorts_have_no_relationships(cohort_a, cohort_b)

    def test_cohort_filter_dependency_updated_changed(self):
        """
        When a cohort's filters are updated to change a dependency, the dependency should be updated.
        """
        cohort_a = self._create_cohort(name="Test Cohort A")
        cohort_b = self._create_cohort(name="Test Cohort B")
        cohort_c = self._create_cohort(
            name="Test Cohort C", filters={"properties": {"values": [{"type": "cohort", "value": cohort_a.id}]}}
        )

        self._assert_depends_on(cohort_c, cohort_a)
        self._assert_cohorts_have_no_relationships(cohort_b)

        cohort_c.filters = {"properties": {"values": [{"type": "cohort", "value": cohort_b.id}]}}
        cohort_c.save()

        self._assert_depends_on(cohort_c, cohort_b)
        self._assert_cohorts_have_no_relationships(cohort_a)

    def test_cohort_filter_dependency_deleted(self):
        """
        When a cohort is deleted, its dependencies should be removed.
        """
        cohort_a = self._create_cohort(name="Test Cohort A")
        cohort_b = self._create_cohort(
            name="Test Cohort B", filters={"properties": {"values": [{"type": "cohort", "value": cohort_a.id}]}}
        )

        self._assert_depends_on(cohort_b, cohort_a)

        cohort_b.delete()

        self._assert_cohorts_have_no_relationships(cohort_a)

    # Groups
    # ------

    def test_cohort_groups_dependency_created(self):
        """
        When a new cohort is created including a groups property that references another cohort,
        a dependency should be created.
        """
        cohort_a = self._create_cohort(name="Test Cohort A")
        cohort_b = self._create_cohort(
            name="Test Cohort B", groups=[{"properties": [{"type": "cohort", "value": cohort_a.id}]}]
        )

        self._assert_depends_on(cohort_b, cohort_a)

    def test_cohort_groups_dependency_updated(self):
        """
        When a cohort's groups properties are updated to add a dependency, the dependency should be created.
        """
        cohort_a = self._create_cohort(name="Test Cohort A")
        cohort_b = self._create_cohort(name="Test Cohort B")

        self._assert_cohorts_have_no_relationships(cohort_a, cohort_b)

        cohort_b.groups = ([{"properties": [{"type": "cohort", "value": cohort_a.id}]}],)
        cohort_b.save()

        self._assert_depends_on(cohort_b, cohort_a)

    def test_cohort_groups_dependency_updated_delete(self):
        """
        When a cohort's groups properties are updated to remove a dependency, the dependency should be removed.
        """
        cohort_a = self._create_cohort(name="Test Cohort A")
        cohort_b = self._create_cohort(
            name="Test Cohort B", groups=[{"properties": [{"type": "cohort", "value": cohort_a.id}]}]
        )

        self._assert_depends_on(cohort_b, cohort_a)

        cohort_b.groups = [{"properties": {}}]
        cohort_b.save()

        self._assert_cohorts_have_no_relationships(cohort_a, cohort_b)

    def test_cohort_groups_dependency_updated_changed(self):
        """
        When a cohort's groups properties are updated to change a dependency, the dependency should be updated.
        """
        cohort_a = self._create_cohort(name="Test Cohort A")
        cohort_b = self._create_cohort(name="Test Cohort B")
        cohort_c = self._create_cohort(
            name="Test Cohort C", groups=[{"properties": [{"type": "cohort", "value": cohort_a.id}]}]
        )

        self._assert_depends_on(cohort_c, cohort_a)
        self._assert_cohorts_have_no_relationships(cohort_b)

        cohort_c.groups = ([{"properties": [{"type": "cohort", "value": cohort_b.id}]}],)
        cohort_c.save()

        self._assert_depends_on(cohort_c, cohort_b)
        self._assert_cohorts_have_no_relationships(cohort_a)

    def test_cohort_groups_dependency_deleted(self):
        """
        When a cohort is deleted, its dependencies should be removed.
        """
        cohort_a = self._create_cohort(name="Test Cohort A")
        cohort_b = self._create_cohort(
            name="Test Cohort B", groups=[{"properties": [{"type": "cohort", "value": cohort_a.id}]}]
        )

        self._assert_depends_on(cohort_b, cohort_a)

        cohort_b.delete()

        self._assert_cohorts_have_no_relationships(cohort_a)

    # Groups + Filters
    # ----------------

    def test_cohort_groups_and_filters(self):
        """
        When a cohort has both groups and filters, filters are prioritized.
        """
        cohort_a = self._create_cohort(name="Test Cohort A")
        cohort_b = self._create_cohort(
            name="Test Cohort B",
            filters={"properties": {"values": []}},
            groups=[{"properties": [{"type": "cohort", "value": cohort_a.id}]}],
        )

        self._assert_cohorts_have_no_relationships(cohort_a, cohort_b)

    def test_cohort_soft_delete(self):
        """
        When a cohort's `delete` column is set to TRUE, its dependencies should be retained.
        This appears to be the current behavior, at least from a UX perspective.
        """
        cohort_a = self._create_cohort(name="Test Cohort A")
        cohort_b = self._create_cohort(
            name="Test Cohort B", groups=[{"properties": [{"type": "cohort", "value": cohort_a.id}]}]
        )

        self._assert_depends_on(cohort_b, cohort_a)

        cohort_a.deleted = True
        cohort_a.save()

        self._assert_depends_on(cohort_b, cohort_a)
