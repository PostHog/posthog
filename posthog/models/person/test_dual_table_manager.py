import uuid

from posthog.test.base import BaseTest

from django.db import connection

from posthog.models import Person, PersonDistinctId, Team
from posthog.models.person.person import PERSON_ID_CUTOFF


class TestDualTablePersonManager(BaseTest):
    """Test dual-table read support in DualPersonManager.

    Creates persons in both old and new tables to validate:
    - .get() method with various kwargs
    - .filter() UNION behavior
    - ID cutoff routing logic
    - Helper methods (get_by_id, get_by_uuid)

    NOTE: posthog_person_new table is created by sqlx migrations in conftest.py
    """

    def setUp(self):
        self.team = Team.objects.create(organization=self.organization)

        # Create person in OLD table (id < 1B)
        self.old_person_uuid = uuid.uuid4()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO posthog_person (id, team_id, uuid, properties, created_at, is_identified)
                VALUES (%s, %s, %s, %s, NOW(), false)
                """,
                [100, self.team.id, str(self.old_person_uuid), '{"name": "old_person"}'],
            )

        # Create person in NEW table (id >= 1B)
        self.new_person_uuid = uuid.uuid4()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO posthog_person_new (id, team_id, uuid, properties, created_at, is_identified)
                VALUES (%s, %s, %s, %s, NOW(), false)
                """,
                [PERSON_ID_CUTOFF + 100, self.team.id, str(self.new_person_uuid), '{"name": "new_person"}'],
            )

        # Create another person in OLD table for filter tests
        self.old_person2_uuid = uuid.uuid4()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO posthog_person (id, team_id, uuid, properties, created_at, is_identified)
                VALUES (%s, %s, %s, %s, NOW(), false)
                """,
                [200, self.team.id, str(self.old_person2_uuid), '{"name": "old_person2"}'],
            )

    def tearDown(self):
        # Clean up test data
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM posthog_person WHERE id IN (100, 200)")
            cursor.execute("DELETE FROM posthog_person_new WHERE id = %s", [PERSON_ID_CUTOFF + 100])

    # Test .get() method
    def test_get_by_pk_old_table(self):
        """Test .get(pk=X) where X < 1B finds person in old table."""
        person = Person.objects.get(pk=100)
        self.assertEqual(person.id, 100)
        self.assertEqual(str(person.uuid), str(self.old_person_uuid))
        self.assertEqual(person.properties["name"], "old_person")

    def test_get_by_pk_new_table(self):
        """Test .get(pk=X) where X >= 1B finds person in new table."""
        person = Person.objects.get(pk=PERSON_ID_CUTOFF + 100)
        self.assertEqual(person.id, PERSON_ID_CUTOFF + 100)
        self.assertEqual(str(person.uuid), str(self.new_person_uuid))
        self.assertEqual(person.properties["name"], "new_person")

    def test_get_by_uuid_old_table(self):
        """Test .get(uuid=X) finds person in old table."""
        person = Person.objects.get(uuid=self.old_person_uuid, team_id=self.team.id)
        self.assertEqual(person.id, 100)
        self.assertEqual(person.properties["name"], "old_person")

    def test_get_by_uuid_new_table(self):
        """Test .get(uuid=X) finds person in new table."""
        person = Person.objects.get(uuid=self.new_person_uuid, team_id=self.team.id)
        self.assertEqual(person.id, PERSON_ID_CUTOFF + 100)
        self.assertEqual(person.properties["name"], "new_person")

    def test_get_by_team_id_finds_both(self):
        """Test .get(team_id=X, uuid=Y) can find persons in either table."""
        # Find old person
        old_person = Person.objects.get(team_id=self.team.id, uuid=self.old_person_uuid)
        self.assertEqual(old_person.id, 100)

        # Find new person
        new_person = Person.objects.get(team_id=self.team.id, uuid=self.new_person_uuid)
        self.assertEqual(new_person.id, PERSON_ID_CUTOFF + 100)

    def test_get_raises_does_not_exist(self):
        """Test .get() raises Person.DoesNotExist when not found in either table."""
        with self.assertRaises(Person.DoesNotExist):
            Person.objects.get(uuid=uuid.uuid4(), team_id=self.team.id)

    # Test .filter() method
    def test_filter_returns_union(self):
        """Test .filter() returns UNION of both tables."""
        persons = list(Person.objects.filter(team_id=self.team.id))
        self.assertEqual(len(persons), 3)  # 2 old + 1 new

        person_ids = {p.id for p in persons}
        self.assertEqual(person_ids, {100, 200, PERSON_ID_CUTOFF + 100})

    def test_filter_can_iterate(self):
        """Test .filter() result can be iterated (union queryset)."""
        count = 0
        for person in Person.objects.filter(team_id=self.team.id):
            count += 1
            self.assertIsInstance(person, Person)
        self.assertEqual(count, 3)

    def test_filter_with_properties(self):
        """Test .filter() with properties filter works on both tables."""
        # This tests that union respects filters
        with connection.cursor() as cursor:
            # Add a person with specific property in old table
            cursor.execute(
                """
                INSERT INTO posthog_person (id, team_id, uuid, properties, created_at, is_identified)
                VALUES (300, %s, %s, %s, NOW(), true)
                """,
                [self.team.id, str(uuid.uuid4()), '{"is_demo": true}'],
            )

        try:
            persons = list(Person.objects.filter(team_id=self.team.id, is_identified=True))
            self.assertEqual(len(persons), 1)
            self.assertEqual(persons[0].properties.get("is_demo"), True)
        finally:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM posthog_person WHERE id = 300")

    # Test helper methods
    def test_get_by_id_old_table(self):
        """Test get_by_id() helper finds person in old table."""
        person = Person.objects.get_by_id(100, team_id=self.team.id)
        self.assertIsNotNone(person)
        self.assertEqual(person.id, 100)
        self.assertEqual(str(person.uuid), str(self.old_person_uuid))

    def test_get_by_id_new_table(self):
        """Test get_by_id() helper finds person in new table."""
        person = Person.objects.get_by_id(PERSON_ID_CUTOFF + 100, team_id=self.team.id)
        self.assertIsNotNone(person)
        self.assertEqual(person.id, PERSON_ID_CUTOFF + 100)
        self.assertEqual(str(person.uuid), str(self.new_person_uuid))

    def test_get_by_id_returns_none_if_not_found(self):
        """Test get_by_id() returns None if not found in either table."""
        person = Person.objects.get_by_id(999999, team_id=self.team.id)
        self.assertIsNone(person)

    def test_get_by_uuid_helper_old_table(self):
        """Test get_by_uuid() helper finds person in old table."""
        person = Person.objects.get_by_uuid(self.team.id, str(self.old_person_uuid))
        self.assertIsNotNone(person)
        self.assertEqual(person.id, 100)

    def test_get_by_uuid_helper_new_table(self):
        """Test get_by_uuid() helper finds person in new table."""
        person = Person.objects.get_by_uuid(self.team.id, str(self.new_person_uuid))
        self.assertIsNotNone(person)
        self.assertEqual(person.id, PERSON_ID_CUTOFF + 100)

    def test_get_by_uuid_returns_none_if_not_found(self):
        """Test get_by_uuid() returns None if not found in either table."""
        person = Person.objects.get_by_uuid(self.team.id, str(uuid.uuid4()))
        self.assertIsNone(person)

    # Test actual call patterns found in codebase
    def test_split_person_pattern(self):
        """Test pattern: Person.objects.get(pk=person_id) from split_person.py."""
        # This is the pattern used in posthog/tasks/split_person.py:13
        person = Person.objects.get(pk=100)
        self.assertEqual(person.id, 100)

        person_new = Person.objects.get(pk=PERSON_ID_CUTOFF + 100)
        self.assertEqual(person_new.id, PERSON_ID_CUTOFF + 100)

    def test_cohort_pattern(self):
        """Test pattern: Person.objects.get(team_id=..., uuid=...) from cohort.py."""
        # This is the pattern used in posthog/api/cohort.py:1125
        person = Person.objects.db_manager("default").get(team_id=self.team.id, uuid=self.old_person_uuid)
        self.assertEqual(person.id, 100)

    def test_filter_iteration_pattern(self):
        """Test pattern: iterating Person.objects.filter() from various files."""
        # This is used in many places, e.g., posthog/api/cohort.py
        person_uuids = [str(p.uuid) for p in Person.objects.filter(team_id=self.team.id)]
        self.assertEqual(len(person_uuids), 3)
        self.assertIn(str(self.old_person_uuid), person_uuids)
        self.assertIn(str(self.new_person_uuid), person_uuids)

    # Test ID cutoff logic
    def test_id_cutoff_routing(self):
        """Test that IDs >= cutoff are routed directly to new table."""
        # ID >= cutoff should ONLY check new table (performance optimization)
        person = Person.objects.get(pk=PERSON_ID_CUTOFF + 100)
        self.assertEqual(person.id, PERSON_ID_CUTOFF + 100)

        # ID < cutoff should check both tables
        person = Person.objects.get(pk=100)
        self.assertEqual(person.id, 100)

    # Test Person instance type
    def test_returned_instances_are_person_type(self):
        """Test that returned instances are Person type (not PersonOld/PersonNew)."""
        person_old = Person.objects.get(pk=100)
        self.assertEqual(type(person_old).__name__, "Person")

        person_new = Person.objects.get(pk=PERSON_ID_CUTOFF + 100)
        self.assertEqual(type(person_new).__name__, "Person")

    # Test FK relations still work
    def test_person_has_distinct_ids_relation(self):
        """Test that Person instances still have persondistinctid_set relation."""
        # Create a distinct ID for old person
        PersonDistinctId.objects.create(person_id=100, team_id=self.team.id, distinct_id="test_distinct_id")

        try:
            person = Person.objects.get(pk=100)
            # Check that FK relation works
            distinct_ids = list(person.persondistinctid_set.all())
            self.assertEqual(len(distinct_ids), 1)
            self.assertEqual(distinct_ids[0].distinct_id, "test_distinct_id")
        finally:
            PersonDistinctId.objects.filter(distinct_id="test_distinct_id").delete()

    # Test filter_by_distinct_ids() helper
    def test_filter_by_distinct_ids_finds_old_table(self):
        """Test filter_by_distinct_ids() finds persons in old table."""
        # Create a distinct ID for old person
        PersonDistinctId.objects.create(person_id=100, team_id=self.team.id, distinct_id="old_distinct_id")

        try:
            persons = Person.objects.filter_by_distinct_ids(self.team.id, ["old_distinct_id"])
            self.assertEqual(len(persons), 1)
            self.assertEqual(persons[0].id, 100)
            self.assertEqual(type(persons[0]).__name__, "Person")
        finally:
            PersonDistinctId.objects.filter(distinct_id="old_distinct_id").delete()

    def test_filter_by_distinct_ids_finds_new_table(self):
        """Test filter_by_distinct_ids() finds persons in new table."""
        # Create a distinct ID for new person using raw SQL (FK constraint doesn't allow ORM create)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO posthog_persondistinctid (person_id, team_id, distinct_id)
                VALUES (%s, %s, %s)
                """,
                [PERSON_ID_CUTOFF + 100, self.team.id, "new_distinct_id"],
            )

        try:
            persons = Person.objects.filter_by_distinct_ids(self.team.id, ["new_distinct_id"])
            self.assertEqual(len(persons), 1)
            self.assertEqual(persons[0].id, PERSON_ID_CUTOFF + 100)
            self.assertEqual(type(persons[0]).__name__, "Person")
        finally:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM posthog_persondistinctid WHERE distinct_id = %s", ["new_distinct_id"])

    def test_filter_by_distinct_ids_finds_both_tables(self):
        """Test filter_by_distinct_ids() finds persons from both tables in one call."""
        # Create distinct IDs for both persons (use raw SQL for new table person)
        PersonDistinctId.objects.create(person_id=100, team_id=self.team.id, distinct_id="old_distinct_id_2")
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO posthog_persondistinctid (person_id, team_id, distinct_id)
                VALUES (%s, %s, %s)
                """,
                [PERSON_ID_CUTOFF + 100, self.team.id, "new_distinct_id_2"],
            )

        try:
            persons = Person.objects.filter_by_distinct_ids(self.team.id, ["old_distinct_id_2", "new_distinct_id_2"])
            self.assertEqual(len(persons), 2)

            person_ids = {p.id for p in persons}
            self.assertEqual(person_ids, {100, PERSON_ID_CUTOFF + 100})

            # Check all are Person type
            for person in persons:
                self.assertEqual(type(person).__name__, "Person")
        finally:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM posthog_persondistinctid WHERE distinct_id IN ('old_distinct_id_2', 'new_distinct_id_2')"
                )

    def test_filter_by_distinct_ids_has_prefetched_distinct_ids(self):
        """Test that filter_by_distinct_ids() prefetches distinct_ids."""
        # Create multiple distinct IDs for old person
        PersonDistinctId.objects.create(person_id=100, team_id=self.team.id, distinct_id="distinct_1")
        PersonDistinctId.objects.create(person_id=100, team_id=self.team.id, distinct_id="distinct_2")

        try:
            persons = Person.objects.filter_by_distinct_ids(self.team.id, ["distinct_1", "distinct_2"])
            self.assertEqual(len(persons), 1)

            person = persons[0]
            # Access distinct_ids property - should use prefetch, not hit DB
            distinct_ids = person.distinct_ids
            self.assertEqual(len(distinct_ids), 2)
            self.assertIn("distinct_1", distinct_ids)
            self.assertIn("distinct_2", distinct_ids)
        finally:
            PersonDistinctId.objects.filter(distinct_id__in=["distinct_1", "distinct_2"]).delete()

    def test_filter_by_distinct_ids_returns_empty_for_missing(self):
        """Test filter_by_distinct_ids() returns empty list when no persons found."""
        persons = Person.objects.filter_by_distinct_ids(self.team.id, ["nonexistent_distinct_id"])
        self.assertEqual(len(persons), 0)

    # Test exclude() method
    def test_exclude_returns_persons_not_matching_filter(self):
        """Test .exclude() returns UNION of persons not matching filter from both tables."""
        # Exclude person with id=100, should get 2 persons (200 and new person)
        persons = Person.objects.exclude(id=100)
        person_ids = {p.id for p in persons}
        self.assertEqual(len(persons), 2)
        self.assertIn(200, person_ids)
        self.assertIn(PERSON_ID_CUTOFF + 100, person_ids)
        self.assertNotIn(100, person_ids)

    def test_exclude_with_team_filter(self):
        """Test .exclude() with team_id filter works on both tables."""
        # Create person in different team
        other_team = Team.objects.create(organization=self.organization)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO posthog_person (id, team_id, uuid, properties, created_at, is_identified)
                VALUES (999, %s, %s, %s, NOW(), false)
                """,
                [other_team.id, str(uuid.uuid4()), '{"name": "other_team"}'],
            )

        try:
            # Exclude old person, but filter by team - should only affect self.team persons
            persons = Person.objects.filter(team_id=self.team.id).exclude(id=100)
            person_ids = {p.id for p in persons}
            self.assertEqual(len(persons), 2)
            self.assertIn(200, person_ids)
            self.assertIn(PERSON_ID_CUTOFF + 100, person_ids)
            self.assertNotIn(100, person_ids)
            self.assertNotIn(999, person_ids)  # Different team, not included
        finally:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM posthog_person WHERE id = 999")

    # Test filter_by_cohort() method
    def test_filter_by_cohort_finds_persons_in_old_table(self):
        """Test filter_by_cohort() finds persons in old table."""
        from posthog.models.cohort import Cohort, CohortPeople

        # Create cohort
        cohort = Cohort.objects.create(team=self.team, name="Test Cohort")

        # Add person from old table to cohort
        CohortPeople.objects.create(cohort_id=cohort.id, person_id=100)

        try:
            persons = Person.objects.filter_by_cohort(cohort.id)
            self.assertEqual(len(persons), 1)
            self.assertEqual(persons[0].id, 100)
            self.assertEqual(str(persons[0].uuid), str(self.old_person_uuid))
        finally:
            CohortPeople.objects.filter(cohort_id=cohort.id).delete()
            cohort.delete()

    def test_filter_by_cohort_finds_persons_in_new_table(self):
        """Test filter_by_cohort() finds persons in new table."""
        from posthog.models.cohort import Cohort, CohortPeople

        # Create cohort
        cohort = Cohort.objects.create(team=self.team, name="Test Cohort New")

        # Add person from new table to cohort
        CohortPeople.objects.create(cohort_id=cohort.id, person_id=PERSON_ID_CUTOFF + 100)

        try:
            persons = Person.objects.filter_by_cohort(cohort.id)
            self.assertEqual(len(persons), 1)
            self.assertEqual(persons[0].id, PERSON_ID_CUTOFF + 100)
            self.assertEqual(str(persons[0].uuid), str(self.new_person_uuid))
        finally:
            CohortPeople.objects.filter(cohort_id=cohort.id).delete()
            cohort.delete()

    def test_filter_by_cohort_finds_persons_in_both_tables(self):
        """Test filter_by_cohort() finds persons from both old and new tables."""
        from posthog.models.cohort import Cohort, CohortPeople

        # Create cohort
        cohort = Cohort.objects.create(team=self.team, name="Test Cohort Mixed")

        # Add persons from both tables to cohort
        CohortPeople.objects.create(cohort_id=cohort.id, person_id=100)
        CohortPeople.objects.create(cohort_id=cohort.id, person_id=PERSON_ID_CUTOFF + 100)

        try:
            persons = Person.objects.filter_by_cohort(cohort.id)
            person_ids = {p.id for p in persons}
            self.assertEqual(len(persons), 2)
            self.assertIn(100, person_ids)
            self.assertIn(PERSON_ID_CUTOFF + 100, person_ids)
        finally:
            CohortPeople.objects.filter(cohort_id=cohort.id).delete()
            cohort.delete()

    def test_filter_by_cohort_returns_empty_for_empty_cohort(self):
        """Test filter_by_cohort() returns empty list for cohort with no persons."""
        from posthog.models.cohort import Cohort

        # Create empty cohort
        cohort = Cohort.objects.create(team=self.team, name="Empty Cohort")

        try:
            persons = Person.objects.filter_by_cohort(cohort.id)
            self.assertEqual(len(persons), 0)
        finally:
            cohort.delete()

    # Test get_by_distinct_id() method
    def test_get_by_distinct_id_finds_person_in_old_table(self):
        """Test get_by_distinct_id() finds person in old table."""
        # Create distinct ID for old person
        PersonDistinctId.objects.create(person_id=100, team_id=self.team.id, distinct_id="old_distinct_id")

        try:
            person = Person.objects.get_by_distinct_id(self.team.id, "old_distinct_id")
            self.assertIsNotNone(person)
            self.assertEqual(person.id, 100)
            self.assertEqual(str(person.uuid), str(self.old_person_uuid))
        finally:
            PersonDistinctId.objects.filter(distinct_id="old_distinct_id").delete()

    def test_get_by_distinct_id_finds_person_in_new_table(self):
        """Test get_by_distinct_id() finds person in new table."""
        # Create distinct ID for new person using raw SQL (FK constraint)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO posthog_persondistinctid (person_id, team_id, distinct_id)
                VALUES (%s, %s, %s)
                """,
                [PERSON_ID_CUTOFF + 100, self.team.id, "new_distinct_id"],
            )

        try:
            person = Person.objects.get_by_distinct_id(self.team.id, "new_distinct_id")
            self.assertIsNotNone(person)
            self.assertEqual(person.id, PERSON_ID_CUTOFF + 100)
            self.assertEqual(str(person.uuid), str(self.new_person_uuid))
        finally:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM posthog_persondistinctid WHERE distinct_id = %s", ["new_distinct_id"])

    def test_get_by_distinct_id_raises_does_not_exist(self):
        """Test get_by_distinct_id() raises Person.DoesNotExist when not found."""
        with self.assertRaises(Person.DoesNotExist) as cm:
            Person.objects.get_by_distinct_id(self.team.id, "nonexistent_distinct_id")

        self.assertIn("No Person found with distinct_id=nonexistent_distinct_id", str(cm.exception))

    def test_get_by_distinct_id_replaces_reverse_fk_pattern(self):
        """Test get_by_distinct_id() replaces Person.objects.get(persondistinctid__distinct_id=...)"""
        # Create distinct ID for old person
        PersonDistinctId.objects.create(person_id=100, team_id=self.team.id, distinct_id="test_pattern")

        try:
            # New pattern using helper
            person = Person.objects.get_by_distinct_id(self.team.id, "test_pattern")

            # Verify it works the same as the old pattern would have
            self.assertEqual(person.id, 100)
            self.assertEqual(person.team_id, self.team.id)
        finally:
            PersonDistinctId.objects.filter(distinct_id="test_pattern").delete()

    # Test DualPersonQuerySet wrapper
    def test_queryset_count_method(self):
        """Test that .filter().count() returns sum of both tables."""
        queryset = Person.objects.filter(team_id=self.team.id)
        self.assertEqual(queryset.count(), 3)  # 2 old + 1 new

    def test_queryset_count_with_additional_filters(self):
        """Test that .count() works with chained filters."""
        queryset = Person.objects.filter(team_id=self.team.id).filter(id=100)
        self.assertEqual(queryset.count(), 1)

    def test_queryset_filter_chaining(self):
        """Test that .filter() can be chained multiple times."""
        queryset = Person.objects.filter(team_id=self.team.id).filter(id__in=[100, 200])
        self.assertEqual(queryset.count(), 2)

        # Verify the right persons are returned
        person_ids = {p.id for p in queryset}
        self.assertEqual(person_ids, {100, 200})

    def test_queryset_filter_with_q_objects(self):
        """Test that .filter() supports Q objects."""
        from django.db.models import Q

        queryset = Person.objects.filter(team_id=self.team.id).filter(Q(id=100) | Q(id=200))
        self.assertEqual(queryset.count(), 2)

    def test_queryset_exclude_method(self):
        """Test that .exclude() works on QuerySet."""
        queryset = Person.objects.filter(team_id=self.team.id).exclude(id=100)
        self.assertEqual(queryset.count(), 2)

        person_ids = {p.id for p in queryset}
        self.assertNotIn(100, person_ids)
        self.assertIn(200, person_ids)
        self.assertIn(PERSON_ID_CUTOFF + 100, person_ids)

    def test_queryset_order_by(self):
        """Test that .order_by() works on QuerySet."""
        queryset = Person.objects.filter(team_id=self.team.id).order_by("id")
        person_ids = [p.id for p in queryset]
        # Should be sorted: [100, 200, PERSON_ID_CUTOFF + 100]
        self.assertEqual(person_ids[0], 100)
        self.assertEqual(person_ids[1], 200)
        self.assertEqual(person_ids[2], PERSON_ID_CUTOFF + 100)

    def test_queryset_values_list(self):
        """Test that .values_list() works on QuerySet."""
        queryset = Person.objects.filter(team_id=self.team.id)
        uuids = queryset.values_list("uuid", flat=True)

        self.assertEqual(len(uuids), 3)
        uuid_strs = [str(u) for u in uuids]
        self.assertIn(str(self.old_person_uuid), uuid_strs)
        self.assertIn(str(self.new_person_uuid), uuid_strs)
        self.assertIn(str(self.old_person2_uuid), uuid_strs)

    def test_queryset_values_list_multiple_fields(self):
        """Test that .values_list() works with multiple fields."""
        queryset = Person.objects.filter(team_id=self.team.id)
        results = queryset.values_list("id", "uuid")

        self.assertEqual(len(results), 3)
        # Each result should be a tuple of (id, uuid)
        for id_val, uuid_val in results:
            self.assertIsInstance(id_val, int)
            self.assertIsNotNone(uuid_val)

    def test_queryset_slicing(self):
        """Test that QuerySet supports slicing."""
        queryset = Person.objects.filter(team_id=self.team.id).order_by("id")

        # Get first 2 persons
        first_two = queryset[:2]
        self.assertEqual(len(first_two), 2)
        self.assertEqual(first_two[0].id, 100)
        self.assertEqual(first_two[1].id, 200)

        # Get last person
        last_one = queryset[2:3]
        self.assertEqual(len(last_one), 1)
        self.assertEqual(last_one[0].id, PERSON_ID_CUTOFF + 100)

    def test_queryset_iteration(self):
        """Test that QuerySet can be iterated."""
        queryset = Person.objects.filter(team_id=self.team.id)

        count = 0
        for person in queryset:
            count += 1
            self.assertIsInstance(person, Person)

        self.assertEqual(count, 3)

    def test_queryset_len(self):
        """Test that len() works on QuerySet."""
        queryset = Person.objects.filter(team_id=self.team.id)
        self.assertEqual(len(queryset), 3)

    def test_filter_by_cohort_returns_queryset(self):
        """Test that filter_by_cohort() returns DualPersonQuerySet."""
        from posthog.models.cohort import Cohort, CohortPeople

        cohort = Cohort.objects.create(team=self.team, name="Test QuerySet Cohort")
        CohortPeople.objects.create(cohort_id=cohort.id, person_id=100)
        CohortPeople.objects.create(cohort_id=cohort.id, person_id=200)

        try:
            queryset = Person.objects.filter_by_cohort(cohort.id)

            # Should support .count()
            self.assertEqual(queryset.count(), 2)

            # Should support further filtering
            filtered = queryset.filter(id=100)
            self.assertEqual(filtered.count(), 1)

            # Should support iteration
            person_ids = {p.id for p in queryset}
            self.assertEqual(person_ids, {100, 200})
        finally:
            CohortPeople.objects.filter(cohort_id=cohort.id).delete()
            cohort.delete()

    def test_exclude_cohort_returns_queryset(self):
        """Test that exclude_cohort() returns DualPersonQuerySet."""
        from posthog.models.cohort import Cohort, CohortPeople

        cohort = Cohort.objects.create(team=self.team, name="Test Exclude QuerySet")
        CohortPeople.objects.create(cohort_id=cohort.id, person_id=100)

        try:
            queryset = Person.objects.exclude_cohort(cohort.id)

            # Should exclude person with id=100
            person_ids = {p.id for p in queryset}
            self.assertNotIn(100, person_ids)

            # Should support .count()
            # Note: This will count ALL persons not in cohort (not filtered by team)
            count = queryset.count()
            self.assertGreater(count, 0)
        finally:
            CohortPeople.objects.filter(cohort_id=cohort.id).delete()

    def test_all_returns_dual_queryset(self):
        """Test that .all() returns DualPersonQuerySet with persons from both tables."""
        from posthog.models.person.person import DualPersonQuerySet

        queryset = Person.objects.all()

        # Should return DualPersonQuerySet
        self.assertIsInstance(queryset, DualPersonQuerySet)

        # Should be able to filter by team
        team_persons = queryset.filter(team_id=self.team.id)
        person_uuids = {str(p.uuid) for p in team_persons}

        # Should include both old and new persons
        self.assertIn(str(self.old_person_uuid), person_uuids)
        self.assertIn(str(self.new_person_uuid), person_uuids)

    def test_prefetch_related_on_queryset(self):
        """Test that .prefetch_related() works on DualPersonQuerySet."""
        from django.db.models import Prefetch

        # Create distinct IDs for both persons
        PersonDistinctId.objects.create(team=self.team, person_id=100, distinct_id="old_distinct_id")
        PersonDistinctId.objects.create(team=self.team, person_id=PERSON_ID_CUTOFF + 100, distinct_id="new_distinct_id")

        queryset = Person.objects.filter(team_id=self.team.id)
        queryset = queryset.prefetch_related(Prefetch("persondistinctid_set", to_attr="distinct_ids_cache"))

        persons = list(queryset)

        # Should have prefetched distinct_ids_cache
        for person in persons:
            self.assertTrue(hasattr(person, "distinct_ids_cache"))
            # Verify the cache is populated
            if person.id == 100:
                distinct_ids = [d.distinct_id for d in person.distinct_ids_cache]
                self.assertIn("old_distinct_id", distinct_ids)
            elif person.id == PERSON_ID_CUTOFF + 100:
                distinct_ids = [d.distinct_id for d in person.distinct_ids_cache]
                self.assertIn("new_distinct_id", distinct_ids)

    def test_only_on_queryset(self):
        """Test that .only() limits fields on DualPersonQuerySet."""
        queryset = Person.objects.filter(team_id=self.team.id)
        queryset = queryset.only("id", "uuid")

        persons = list(queryset)

        # Should return persons
        self.assertEqual(len(persons), 3)  # old_person, new_person, old_person2

        # Accessing only() fields should work
        for person in persons:
            self.assertIsNotNone(person.id)
            self.assertIsNotNone(person.uuid)

    def test_all_with_chained_operations(self):
        """Test that .all() chains properly with filter, prefetch, and only."""
        from django.db.models import Prefetch

        PersonDistinctId.objects.create(team=self.team, person_id=100, distinct_id="chain_test_old")

        queryset = Person.objects.all()
        queryset = queryset.filter(team_id=self.team.id)
        queryset = queryset.prefetch_related(Prefetch("persondistinctid_set", to_attr="distinct_ids_cache"))
        queryset = queryset.only("id", "uuid", "properties")

        persons = list(queryset)

        # Should return persons from both tables
        self.assertGreaterEqual(len(persons), 2)

        # Should have prefetch applied
        old_person = next(p for p in persons if p.id == 100)
        self.assertTrue(hasattr(old_person, "distinct_ids_cache"))
        distinct_ids = [d.distinct_id for d in old_person.distinct_ids_cache]
        self.assertIn("chain_test_old", distinct_ids)

    def test_queryset_has_model_attribute(self):
        """Test that DualPersonQuerySet has .model attribute for compatibility."""
        queryset = Person.objects.filter(team_id=self.team.id)

        # Should have model attribute
        self.assertTrue(hasattr(queryset, "model"))
        self.assertEqual(queryset.model, Person)

    def test_raw_delete_deletes_from_both_tables(self):
        """Test that _raw_delete() deletes from both PersonOld and PersonNew tables."""
        # Create additional person in new table for this test
        new_person_uuid = uuid.uuid4()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO posthog_person_new (id, team_id, uuid, properties, created_at, is_identified)
                VALUES (%s, %s, %s, %s, NOW(), false)
                """,
                [PERSON_ID_CUTOFF + 200, self.team.id, str(new_person_uuid), '{"name": "delete_test"}'],
            )

        # Verify persons exist before delete
        queryset_before = Person.objects.filter(team_id=self.team.id)
        person_uuids_before = {str(p.uuid) for p in queryset_before}
        self.assertIn(str(self.old_person_uuid), person_uuids_before)
        self.assertIn(str(new_person_uuid), person_uuids_before)

        # Delete using _raw_delete (simulating delete_bulky_postgres_data pattern)
        queryset = Person.objects.filter(team_id=self.team.id)
        queryset._raw_delete(using=None)  # None means use router

        # Verify persons are deleted from both tables
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM posthog_person WHERE team_id = %s", [self.team.id])
            old_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM posthog_person_new WHERE team_id = %s", [self.team.id])
            new_count = cursor.fetchone()[0]

        self.assertEqual(old_count, 0, "Old table should be empty after _raw_delete")
        self.assertEqual(new_count, 0, "New table should be empty after _raw_delete")

    def test_queryset_db_routing_uses_router(self):
        """Test that DualPersonQuerySet respects database router when db is None."""
        queryset = Person.objects.filter(team_id=self.team.id)

        # When db is None, should use router (not force "default")
        self.assertIsNone(queryset.db)

        # The underlying PersonOld/PersonNew queries should be routed to persons_db
        # We can't easily test the actual routing in unit tests, but we can verify
        # that we're not forcing "default" which would bypass the router
        from django.db import router

        from posthog.models.person.person import PersonNew, PersonOld

        # Verify router routes PersonOld/PersonNew to persons_db
        self.assertEqual(router.db_for_write(PersonOld), "persons_db_writer")
        self.assertEqual(router.db_for_write(PersonNew), "persons_db_writer")
