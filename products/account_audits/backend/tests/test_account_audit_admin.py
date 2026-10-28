import base64

from posthog.test.base import BaseTest

from django.contrib.admin.models import LogEntry
from django.urls import reverse

from posthog.models import User

from products.account_audits.backend.models import AccountAuditCredential


class TestAccountAuditCredentialAdmin(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.client.force_login(self.user)
        self.add_url = reverse("admin:account_audits_accountauditcredential_add")
        self.add_data = {"is_active": "on"}

    def test_admin_provisions_once_then_allows_overlap_and_revocation_without_exposing_secret(self) -> None:
        site_url = "https://eu.posthog.com"
        self.enterContext(self.settings(SITE_URL=site_url))
        other_staff = User.objects.create(email="other-staff@example.com", is_staff=True)
        self.assertNotContains(self.client.get(self.add_url), 'name="created_by"')
        response = self.client.post(self.add_url, {**self.add_data, "created_by": other_staff.pk})
        self.assertEqual(response.status_code, 200)
        credential = AccountAuditCredential.objects.get()
        self.assertEqual(credential.created_by_id, self.user.pk)
        secret = credential.signing_secret
        self.assertTrue(secret.startswith("whsec_"))
        self.assertEqual(len(base64.b64decode(secret.removeprefix("whsec_"))), 32)
        self.assertContains(response, secret)
        self.assertContains(response, f"{site_url}{reverse('account_audits-start')}")
        self.assertIn("no-store", response.headers["Cache-Control"])
        change_url = reverse("admin:account_audits_accountauditcredential_change", args=[credential.pk])
        self.assertNotContains(self.client.get(change_url), secret)
        self.assertNotContains(
            self.client.get(reverse("admin:account_audits_accountauditcredential_changelist")), secret
        )
        self.assertFalse(LogEntry.objects.filter(change_message__contains=secret).exists())

        response = self.client.post(self.add_url, self.add_data)
        self.assertEqual(response.status_code, 200)
        replacement = AccountAuditCredential.objects.exclude(pk=credential.pk).get()
        self.assertNotEqual(replacement.signing_secret, secret)
        credential.refresh_from_db()
        self.assertTrue(credential.is_active)

        response = self.client.post(change_url, {"created_by": "", "signing_secret": "replacement"})
        self.assertEqual(response.status_code, 302)
        credential.refresh_from_db()
        self.assertFalse(credential.is_active)
        self.assertEqual(credential.created_by_id, self.user.pk)
        self.assertEqual(credential.signing_secret, secret)
        replacement.refresh_from_db()
        self.assertTrue(replacement.is_active)
