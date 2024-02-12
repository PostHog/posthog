from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership


def can_user_edit_feature_flag(request, feature_flag):
    # self hosted check for enterprise models that may not exist
    try:
        from ee.models.feature_flag_role_access import FeatureFlagRoleAccess
        from ee.models.organization_resource_access import OrganizationResourceAccess
    except:
        return True
    else:
        if not request.user.organization.is_feature_available(AvailableFeature.ROLE_BASED_ACCESS):
            return True
        if hasattr(feature_flag, "created_by") and feature_flag.created_by and feature_flag.created_by == request.user:
            return True
        if (
            request.user.organization_memberships.get(organization=request.user.organization).level
            >= OrganizationMembership.Level.ADMIN
        ):
            return True
        all_role_memberships = request.user.role_memberships.select_related("role").all()
        try:
            feature_flag_resource_access = OrganizationResourceAccess.objects.get(
                organization=request.user.organization,
                resource=OrganizationResourceAccess.Resources.FEATURE_FLAGS,
            )
            if feature_flag_resource_access.access_level >= OrganizationResourceAccess.AccessLevel.CAN_ALWAYS_EDIT:
                return True
            org_level = feature_flag_resource_access.access_level
        except OrganizationResourceAccess.DoesNotExist:
            org_level = OrganizationResourceAccess.AccessLevel.CAN_ALWAYS_EDIT

        role_level = max(
            [membership.role.feature_flags_access_level for membership in all_role_memberships],
            default=0,
        )

        if role_level == 0:
            final_level = org_level
        else:
            final_level = role_level
        if final_level == OrganizationResourceAccess.AccessLevel.CAN_ONLY_VIEW:
            can_edit = FeatureFlagRoleAccess.objects.filter(
                feature_flag__id=feature_flag.pk,
                role__id__in=[membership.role.pk for membership in all_role_memberships],
            ).exists()
            return can_edit
        else:
            return final_level == OrganizationResourceAccess.AccessLevel.CAN_ALWAYS_EDIT
