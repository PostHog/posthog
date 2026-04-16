# ruleid: organization-membership-regular-manager
memberships = OrganizationMembership.objects.filter(organization=org).all()

# ruleid: organization-membership-regular-manager
memberships = OrganizationMembership.objects.filter(organization_id=org.id, level__gte=1)

# ok: organization-membership-regular-manager
memberships = OrganizationMembership.regular.filter(organization=org).all()

# ok: organization-membership-regular-manager
memberships = OrganizationMembership.regular.filter(organization_id=org.id)

# ok: organization-membership-regular-manager
# (unrelated filter, no organization kwarg, e.g., looking up a specific membership)
membership = OrganizationMembership.objects.get(user=user, id=membership_id)
