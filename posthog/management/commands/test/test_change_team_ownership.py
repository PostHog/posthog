import pytest
from django.core.management import CommandError, call_command

from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team


@pytest.fixture
def organization():
    organization = create_organization("old")
    yield organization
    organization.delete()


@pytest.fixture
def new_organization():
    organization = create_organization("new")
    yield organization
    organization.delete()


@pytest.fixture
def team(organization):
    team = create_team(organization=organization)
    yield team
    team.delete()


def test_change_team_ownership_required_parameters():
    with pytest.raises(CommandError):
        call_command("change_team_ownership", "--team-id=123")

    with pytest.raises(CommandError):
        call_command("change_team_ownership", "--organization-id=123")


@pytest.mark.django_db
def test_change_team_ownership_dry_run(organization, new_organization, team):
    """Test organization doesn't change in a dry run"""
    call_command(
        "change_team_ownership",
        f"--team-id={team.id}",
        f"--organization-id={new_organization.id}",
    )

    team.refresh_from_db()

    assert team.organization_id == organization.id


@pytest.mark.django_db
def test_change_team_ownership_fails_with_same_organization(organization, team):
    """Test command fails if trying to change to same organization."""
    with pytest.raises(CommandError):
        call_command(
            "change_team_ownership",
            f"--team-id={team.id}",
            f"--organization-id={organization.id}",
            "--live-run",
        )

    team.refresh_from_db()

    assert team.organization_id == organization.id


@pytest.mark.django_db
def test_change_team_ownership(new_organization, team):
    """Test the command works."""
    call_command(
        "change_team_ownership",
        f"--team-id={team.id}",
        f"--organization-id={new_organization.id}",
        "--live-run",
    )

    team.refresh_from_db()

    assert team.organization_id == new_organization.id
