from io import StringIO

from posthog.test.base import BaseTest

from django.core.management import call_command
from django.utils import timezone

from django_otp.util import random_hex

from posthog.models.user import User


class TestFindDuplicateUsersByEmailCase(BaseTest):
    def _create_case_variants(self) -> tuple[User, User]:
        used = User.objects.create_and_join(self.organization, "twins@example.com", "testpass123", "Used")
        # Bypass the manager, which lowercases emails, to recreate a legacy mixed-case row.
        User.objects.filter(id=used.id).update(email="Twins@Example.com", last_login=timezone.now())
        abandoned = User.objects.create_user(email="twins@example.com", password="testpass123", first_name="Abandoned")
        return User.objects.get(id=used.id), abandoned

    def test_reports_case_variant_duplicates_only(self):
        used, abandoned = self._create_case_variants()
        out = StringIO()

        call_command("find_duplicate_users_by_email_case", stdout=out)
        output = out.getvalue()

        self.assertIn(f"keep  id={used.id}", output)
        self.assertIn(f"dupe  id={abandoned.id}", output)
        self.assertNotIn(self.user.email, output)

    def test_deactivate_abandoned_spares_accounts_holding_anything(self):
        _used, abandoned = self._create_case_variants()
        abandoned.totpdevice_set.create(name="default", key=random_hex(), digits=6)  # type: ignore[attr-defined]

        call_command("find_duplicate_users_by_email_case", "--deactivate-abandoned", stdout=StringIO())

        abandoned.refresh_from_db()
        self.assertTrue(abandoned.is_active)

    def test_deactivate_abandoned_deactivates_the_empty_twin(self):
        used, abandoned = self._create_case_variants()

        call_command("find_duplicate_users_by_email_case", "--deactivate-abandoned", stdout=StringIO())

        abandoned.refresh_from_db()
        used.refresh_from_db()
        self.assertFalse(abandoned.is_active)
        self.assertTrue(used.is_active)
