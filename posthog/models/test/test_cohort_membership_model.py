from posthog.test.base import BaseTest

from posthog.models import Cohort, CohortMembership, Person


class TestCohortMembership(BaseTest):
    def setUp(self):
        super().setUp()
        self.person = Person.objects.create(team=self.team)
        self.cohort = Cohort.objects.create(team=self.team, name="Test Cohort")

    def test_create_cohort_membership(self):
        membership = CohortMembership.objects.create(
            person_id=self.person.id, cohort_id=self.cohort.id, team_id=self.team.id
        )

        self.assertEqual(membership.person_id, self.person.id)
        self.assertEqual(membership.cohort_id, self.cohort.id)
        self.assertEqual(membership.team_id, self.team.id)
        self.assertFalse(membership.is_deleted)

    def test_str_representation_active(self):
        membership = CohortMembership.objects.create(
            person_id=self.person.id, cohort_id=self.cohort.id, team_id=self.team.id, is_deleted=False
        )

        expected = f"Person {self.person.id} in Cohort {self.cohort.id}"
        self.assertEqual(str(membership), expected)

    def test_str_representation_deleted(self):
        membership = CohortMembership.objects.create(
            person_id=self.person.id, cohort_id=self.cohort.id, team_id=self.team.id, is_deleted=True
        )

        expected = f"Person {self.person.id} not in Cohort {self.cohort.id}"
        self.assertEqual(str(membership), expected)

    def test_soft_delete_preserves_record(self):
        membership = CohortMembership.objects.create(
            person_id=self.person.id, cohort_id=self.cohort.id, team_id=self.team.id
        )

        # Soft delete
        membership.is_deleted = True
        membership.save()

        # Record should still exist
        self.assertTrue(CohortMembership.objects.filter(id=membership.id).exists())

        # But should be marked as deleted
        updated_membership = CohortMembership.objects.get(id=membership.id)
        self.assertTrue(updated_membership.is_deleted)

    def test_soft_delete_behavior(self):
        membership = CohortMembership.objects.create(
            person_id=self.person.id, cohort_id=self.cohort.id, team_id=self.team.id
        )

        # Initially not deleted
        self.assertFalse(membership.is_deleted)

        # Soft delete
        membership.is_deleted = True
        membership.save()

        updated_membership = CohortMembership.objects.get(id=membership.id)
        self.assertTrue(updated_membership.is_deleted)

    def test_team_isolation(self):
        """Test that memberships are properly isolated between teams"""
        other_team = self.organization.teams.create(name="Other Team")
        other_person = Person.objects.create(team=other_team)
        other_cohort = Cohort.objects.create(team=other_team, name="Other Team Cohort")

        membership1 = CohortMembership.objects.create(
            person_id=self.person.id, cohort_id=self.cohort.id, team_id=self.team.id
        )

        membership2 = CohortMembership.objects.create(
            person_id=other_person.id, cohort_id=other_cohort.id, team_id=other_team.id
        )

        self.assertNotEqual(membership1.team_id, membership2.team_id)
        self.assertNotEqual(membership1.cohort_id, membership2.cohort_id)
        self.assertNotEqual(membership1.person_id, membership2.person_id)

        all_memberships = CohortMembership.objects.all()

        team1_memberships = [m for m in all_memberships if m.team_id == self.team.id]
        team2_memberships = [m for m in all_memberships if m.team_id == other_team.id]

        self.assertEqual(len(team1_memberships), 1)
        self.assertEqual(len(team2_memberships), 1)
        self.assertEqual(team1_memberships[0].id, membership1.id)
        self.assertEqual(team2_memberships[0].id, membership2.id)
