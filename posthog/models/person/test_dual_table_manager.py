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
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Create posthog_person_new table for testing
        # Since PersonNew has managed=False, Django won't create it
        with connection.cursor() as cursor:
            # Create table with same structure as posthog_person
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS posthog_person_new (
                    LIKE posthog_person INCLUDING DEFAULTS
                )
            """)

    @classmethod
    def tearDownClass(cls):
        # Clean up the test table
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS posthog_person_new CASCADE")
        super().tearDownClass()

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
