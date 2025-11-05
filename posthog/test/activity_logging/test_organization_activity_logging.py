from posthog.models import Organization, User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.organization import OrganizationMembership
from posthog.models.organization_invite import OrganizationInvite
from posthog.models.uploaded_media import UploadedMedia
from posthog.test.activity_log_utils import ActivityLogTestHelper


class TestOrganizationActivityLogging(ActivityLogTestHelper):
    def test_organization_creation_activity_logging(self):
        organization = self.create_organization("Test Organization")

        log = ActivityLog.objects.filter(
            organization_id=organization["id"], scope="Organization", activity="created"
        ).first()

        assert log is not None
        self.assertEqual(log.activity, "created")
        self.assertEqual(log.item_id, str(organization["id"]))
        self.assertEqual(log.user, self.user)
        self.assertEqual(log.detail["name"], organization["name"])

    def test_organization_update_activity_logging(self):
        organization = self.create_organization("Original Organization")
        self.update_organization(organization["id"], {"name": "Updated Organization"})

        log = ActivityLog.objects.filter(organization_id=organization["id"], activity="updated").first()

        assert log is not None
        self.assertEqual(log.activity, "updated")
        self.assertEqual(log.user, self.user)
        self.assertEqual(log.detail["name"], "Updated Organization")

        changes = log.detail.get("changes", [])
        name_change = next((c for c in changes if c["field"] == "organization name"), None)
        assert name_change is not None
        self.assertEqual(name_change["before"], "Original Organization")
        self.assertEqual(name_change["after"], "Updated Organization")

    def test_organization_security_settings_activity_logging(self):
        organization = self.create_organization("Security Test Org")
        self.update_organization(organization["id"], {"enforce_2fa": True})

        log = ActivityLog.objects.filter(organization_id=organization["id"], activity="updated").first()

        assert log is not None
        changes = log.detail.get("changes", [])
        enforce_2fa_change = next((c for c in changes if c["field"] == "two-factor authentication requirement"), None)
        assert enforce_2fa_change is not None
        self.assertEqual(enforce_2fa_change["after"], True)

    def test_organization_member_invite_permissions_activity_logging(self):
        organization = self.create_organization("Permissions Test Org")
        self.update_organization(organization["id"], {"members_can_invite": False})

        log = (
            ActivityLog.objects.filter(organization_id=organization["id"], activity="updated")
            .order_by("-created_at")
            .first()
        )
        assert log is not None
        changes = log.detail.get("changes", [])
        invite_change = next((c for c in changes if c["field"] == "member invitation permissions"), None)
        assert invite_change is not None
        self.assertEqual(invite_change["after"], False)

        self.update_organization(organization["id"], {"members_can_use_personal_api_keys": False})

        log = (
            ActivityLog.objects.filter(organization_id=organization["id"], activity="updated")
            .order_by("-created_at")
            .first()
        )
        assert log is not None
        changes = log.detail.get("changes", [])
        api_keys_change = next((c for c in changes if c["field"] == "personal API key permissions"), None)
        assert api_keys_change is not None
        self.assertEqual(api_keys_change["after"], False)

    def test_organization_sharing_settings_activity_logging(self):
        organization = self.create_organization("Sharing Test Org")
        self.update_organization(organization["id"], {"allow_publicly_shared_resources": False})

        log = ActivityLog.objects.filter(organization_id=organization["id"], activity="updated").first()
        assert log is not None
        changes = log.detail.get("changes", [])
        sharing_change = next((c for c in changes if c["field"] == "public sharing permissions"), None)
        assert sharing_change is not None
        self.assertEqual(sharing_change["after"], False)

    def test_organization_multiple_changes_activity_logging(self):
        organization = self.create_organization("Multi Change Test Org")
        self.update_organization(
            organization["id"],
            {"name": "New Multi Change Org", "enforce_2fa": True, "members_can_invite": False},
        )

        log = ActivityLog.objects.filter(organization_id=organization["id"], activity="updated").first()
        assert log is not None
        changes = log.detail.get("changes", [])
        field_changes = {c["field"]: c for c in changes}

        assert "organization name" in field_changes
        assert "two-factor authentication requirement" in field_changes
        assert "member invitation permissions" in field_changes
        self.assertEqual(field_changes["organization name"]["after"], "New Multi Change Org")
        self.assertEqual(field_changes["two-factor authentication requirement"]["after"], True)
        self.assertEqual(field_changes["member invitation permissions"]["after"], False)

    def test_organization_name_change_logging(self):
        organization = self.create_organization("Name Test Org")
        self.update_organization(organization["id"], {"name": "Name Test Org Updated"})

        log = ActivityLog.objects.filter(organization_id=organization["id"], activity="updated").first()
        assert log is not None
        changes = log.detail.get("changes", [])
        name_change = next((c for c in changes if c["field"] == "organization name"), None)
        assert name_change is not None
        self.assertEqual(name_change["after"], "Name Test Org Updated")

    def test_organization_experiment_stats_method_logging(self):
        organization = self.create_organization("Experiments Test Org")
        self.update_organization(organization["id"], {"default_experiment_stats_method": "frequentist"})

        log = ActivityLog.objects.filter(organization_id=organization["id"], activity="updated").first()
        assert log is not None
        changes = log.detail.get("changes", [])
        stats_change = next((c for c in changes if c["field"] == "default experiment stats method"), None)
        assert stats_change is not None
        self.assertEqual(stats_change["after"], "frequentist")

    def test_organization_member_join_email_logging(self):
        organization = self.create_organization("Email Preferences Test Org")
        self.update_organization(organization["id"], {"is_member_join_email_enabled": False})

        log = ActivityLog.objects.filter(organization_id=organization["id"], activity="updated").first()
        assert log is not None
        changes = log.detail.get("changes", [])
        email_change = next((c for c in changes if c["field"] == "member join email notifications"), None)
        assert email_change is not None
        self.assertEqual(email_change["after"], False)

    def test_organization_2fa_enforcement_logging(self):
        organization = self.create_organization("2FA Test Org")
        self.update_organization(organization["id"], {"enforce_2fa": True})

        log = ActivityLog.objects.filter(organization_id=organization["id"], activity="updated").first()
        assert log is not None
        changes = log.detail.get("changes", [])
        twofa_change = next((c for c in changes if c["field"] == "two-factor authentication requirement"), None)
        assert twofa_change is not None
        self.assertEqual(twofa_change["after"], True)

    def test_organization_membership_creation_activity_logging(self):
        org_response = self.create_organization("Test Membership Org")
        org = Organization.objects.get(id=org_response["id"])
        new_user = User.objects.create_user(
            email="testmember@example.com", password="testpass123", first_name="Test", last_name="Member"
        )
        membership = new_user.join(organization=org, level=OrganizationMembership.Level.MEMBER)

        log = ActivityLog.objects.filter(
            organization_id=org.id, scope="OrganizationMembership", activity="created", item_id=str(membership.id)
        ).first()

        assert log is not None
        self.assertEqual(log.activity, "created")
        self.assertEqual(log.item_id, str(membership.id))
        self.assertIn("joined", log.detail["name"])
        self.assertIn("testmember@example.com", log.detail["name"])

        context = log.detail.get("context", {})
        self.assertEqual(context["user_email"], "testmember@example.com")
        self.assertEqual(context["organization_name"], "Test Membership Org")

    def test_organization_membership_deletion_activity_logging(self):
        org_response = self.create_organization("Test Delete Membership Org")
        org = Organization.objects.get(id=org_response["id"])
        member_user = User.objects.create_user(
            email="deletemember@example.com", password="testpass123", first_name="Delete", last_name="Member"
        )
        membership = member_user.join(organization=org, level=OrganizationMembership.Level.MEMBER)
        membership_id = str(membership.id)

        response = self.client.delete(f"/api/organizations/{org.id}/members/{member_user.uuid}/")
        self.assertEqual(response.status_code, 204)

        log = ActivityLog.objects.filter(
            organization_id=org.id, scope="OrganizationMembership", activity="deleted"
        ).first()

        assert log is not None
        self.assertEqual(log.activity, "deleted")
        self.assertEqual(log.item_id, membership_id)
        self.assertIn("left", log.detail["name"])
        self.assertIn("deletemember@example.com", log.detail["name"])

        context = log.detail.get("context", {})
        self.assertEqual(context["user_email"], "deletemember@example.com")
        self.assertEqual(context["organization_name"], "Test Delete Membership Org")

    def test_organization_membership_level_update_activity_logging(self):
        org_response = self.create_organization("Test Update Membership Org")
        org = Organization.objects.get(id=org_response["id"])
        member_user = User.objects.create_user(
            email="updatemember@example.com", password="testpass123", first_name="Update", last_name="Member"
        )
        membership = member_user.join(organization=org, level=OrganizationMembership.Level.MEMBER)

        response = self.client.patch(
            f"/api/organizations/{org.id}/members/{member_user.uuid}/", {"level": 8}, format="json"
        )
        self.assertEqual(response.status_code, 200)

        log = ActivityLog.objects.filter(
            organization_id=org.id, scope="OrganizationMembership", activity="updated"
        ).first()

        assert log is not None
        self.assertEqual(log.activity, "updated")
        self.assertEqual(log.item_id, str(membership.id))
        self.assertIn("membership updated", log.detail["name"])

        changes = log.detail.get("changes", [])
        level_change = next((c for c in changes if c["field"] == "level"), None)
        assert level_change is not None
        self.assertEqual(level_change["before"], 1)
        self.assertEqual(level_change["after"], 8)

    def test_organization_invite_creation_activity_logging(self):
        organization = self.create_organization("Test Invite Org")
        org = Organization.objects.get(id=organization["id"])

        # Use API to create the invite to properly set user context
        response = self.client.post(
            f"/api/organizations/{org.id}/invites/",
            {
                "target_email": "invitee@example.com",
                "level": OrganizationMembership.Level.MEMBER,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        invite = OrganizationInvite.objects.get(target_email="invitee@example.com")

        log = ActivityLog.objects.filter(
            organization_id=org.id, scope="OrganizationInvite", activity="created", item_id=str(invite.id)
        ).first()

        assert log is not None
        self.assertEqual(log.activity, "created")
        self.assertEqual(log.item_id, str(invite.id))
        self.assertEqual(log.user, self.user)
        self.assertIn("invited user invitee@example.com", log.detail["name"])
        self.assertIn("Test Invite Org", log.detail["name"])

        context = log.detail.get("context", {})
        self.assertEqual(context["target_email"], "invitee@example.com")
        self.assertEqual(context["organization_name"], "Test Invite Org")
        self.assertEqual(context["inviter_user_email"], self.user.email)
        self.assertEqual(context["level"], "member")

    def test_organization_invite_deletion_activity_logging(self):
        organization = self.create_organization("Test Delete Invite Org")
        org = Organization.objects.get(id=organization["id"])

        response = self.client.post(
            f"/api/organizations/{org.id}/invites/",
            {
                "target_email": "delete-invitee@example.com",
                "level": OrganizationMembership.Level.ADMIN,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        invite = OrganizationInvite.objects.get(target_email="delete-invitee@example.com")
        invite_id = str(invite.id)

        response = self.client.delete(f"/api/organizations/{org.id}/invites/{invite.id}/")
        self.assertEqual(response.status_code, 204)

        log = ActivityLog.objects.filter(organization_id=org.id, scope="OrganizationInvite", activity="deleted").first()

        assert log is not None
        self.assertEqual(log.activity, "deleted")
        self.assertEqual(log.item_id, invite_id)
        self.assertIn("cancelled", log.detail["name"])
        self.assertIn("delete-invitee@example.com", log.detail["name"])

        context = log.detail.get("context", {})
        self.assertEqual(context["target_email"], "delete-invitee@example.com")
        self.assertEqual(context["organization_name"], "Test Delete Invite Org")
        self.assertEqual(context["level"], "administrator")

    def test_organization_logo_media_update_activity_logging(self):
        organization = self.create_organization("Logo Test Org")
        org = Organization.objects.get(id=organization["id"])

        media = UploadedMedia.objects.create(media_location="test-logo.png", team_id=self.team.id, created_by=self.user)

        response = self.client.patch(
            f"/api/organizations/{org.id}/",
            {"logo_media_id": str(media.id)},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

        log = (
            ActivityLog.objects.filter(organization_id=org.id, scope="Organization", activity="updated")
            .order_by("-created_at")
            .first()
        )

        assert log is not None
        self.assertEqual(log.activity, "updated")
        self.assertEqual(log.user, self.user)

        changes = log.detail.get("changes", [])
        logo_change = next((c for c in changes if c["field"] == "logo_media"), None)
        assert logo_change is not None
        self.assertEqual(logo_change["action"], "created")
        self.assertEqual(logo_change["after"]["id"], str(media.id))
        self.assertEqual(logo_change["after"]["media_location"], "test-logo.png")

        response = self.client.patch(
            f"/api/organizations/{org.id}/",
            {"logo_media_id": None},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

        log = (
            ActivityLog.objects.filter(organization_id=org.id, scope="Organization", activity="updated")
            .order_by("-created_at")
            .first()
        )

        assert log is not None
        changes = log.detail.get("changes", [])
        logo_removal = next((c for c in changes if c["field"] == "logo_media"), None)
        assert logo_removal is not None
        self.assertEqual(logo_removal["action"], "deleted")
        self.assertEqual(logo_removal["before"]["id"], str(media.id))
