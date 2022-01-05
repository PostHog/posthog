from typing import Any, Dict, Optional, Tuple

from posthog.models import Organization, OrganizationMembership, Team, User

from . import hogflix


def prepare_demo(
    *,
    email: str,
    first_name: str,
    password: Optional[str] = None,
    organization_name: str = hogflix.ORGANIZATION_NAME,
    team_fields: Optional[Dict[str, Any]] = None,
    no_data: bool = False,
) -> Tuple[Organization, Team, User]:
    # If there's an email collision in signup in the demo environment, we treat it as a login
    existing_user = User.objects.filter(email=email).first()
    if existing_user is None:
        organization = Organization.objects.create(name=organization_name)
        new_user = User.objects.create_and_join(
            organization, email, password, first_name, OrganizationMembership.Level.ADMIN
        )
        team = hogflix.hogflix_data_generator.create_team(
            organization, new_user, simulate_journeys=not no_data, **(team_fields or {})
        )
        return organization, team, new_user
    else:
        return existing_user.organization, existing_user.team, existing_user
