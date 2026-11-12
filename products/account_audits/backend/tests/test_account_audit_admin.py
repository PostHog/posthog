import base64

from posthog.test.base import BaseTest

from django.contrib.messages import get_messages
from django.urls import reverse

from products.account_audits.backend.models import AccountAuditCredential

CREATE_URL = "/admin/console/tools/account-audit-credentials/create/"


class TestAccountAuditCredentialAdmin(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.client.force_login(self.user)

    def test_console_creates_once_then_allows_overlap_and_revocation_without_exposing_secret(self) -> None:
        site_url = "https://eu.posthog.com"
        self.enterContext(self.settings(SITE_URL=site_url))
        self.assertEqual(self.client.post(CREATE_URL, {}).status_code, 400)
        self.assertFalse(AccountAuditCredential.objects.exists())

        created = self.client.post(CREATE_URL, {"reason": "Set up the audit workflow"})
        self.assertEqual(created.status_code, 302)
        credential = AccountAuditCredential.objects.get()
        self.assertEqual(credential.created_by_id, self.user.pk)
        secret = credential.signing_secret
        self.assertTrue(secret.startswith("whsec_"))
        self.assertEqual(len(base64.b64decode(secret.removeprefix("whsec_"))), 32)
        self.assertNotIn(secret, created["Location"])
        result = self.client.get(created["Location"])
        self.assertContains(result, secret)
        self.assertContains(result, str(credential.public_key_id))
        self.assertContains(result, f"{site_url}{reverse('account_audits-start')}")
        self.assertIn("no-store", result.headers["Cache-Control"])
        self.assertFalse(any(secret in str(message) for message in get_messages(result.wsgi_request)))
        change_url = reverse("admin:account_audits_accountauditcredential_change", args=[credential.pk])
        self.assertNotContains(self.client.get(change_url), secret)
        self.assertNotContains(
            self.client.get(reverse("admin:account_audits_accountauditcredential_changelist")), secret
        )

        self.client.post(CREATE_URL, {"reason": "Rotate the audit workflow credential"})
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

    def test_old_add_url_opens_the_console_form(self) -> None:
        response = self.client.post("/admin/account_audits/accountauditcredential/add/?_popup=1", {"is_active": "on"})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"{CREATE_URL}?_popup=1")
        self.assertFalse(AccountAuditCredential.objects.exists())
