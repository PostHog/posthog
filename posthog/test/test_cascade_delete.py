import pytest

from posthog.models import Organization, OrganizationMembership, Tag, Team, User
from posthog.test.cascade_delete import delete_skipping_empty_tables


@pytest.mark.django_db
def test_deletes_rows_reached_through_fk_chains_and_nulls_references() -> None:
    organization, other_organization = (Organization.objects.create(name=name) for name in ("deleted", "kept"))
    teams = [Team.objects.create(organization=owner) for owner in (organization, other_organization)]
    for team in teams:
        Tag._base_manager.create(team=team, name="cascade")
    user = User.objects.create_and_join(organization, "cascade@example.com", None)
    organization_ids = [organization.id, other_organization.id]

    delete_skipping_empty_tables(organization)

    assert list(Organization.objects.filter(id__in=organization_ids).values_list("id", flat=True)) == [
        other_organization.id
    ]
    assert list(Team.objects.filter(organization_id__in=organization_ids).values_list("id", flat=True)) == [teams[1].id]
    assert list(
        Tag._base_manager.filter(team_id__in=[team.id for team in teams]).values_list("team_id", flat=True)
    ) == [teams[1].id]
    assert not OrganizationMembership.objects.filter(user=user).exists()
    user.refresh_from_db()
    assert user.current_organization_id is None
