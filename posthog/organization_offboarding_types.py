from posthog.dataclasses import frozen


@frozen
class OffboardingResource:
    id: str
    resource_id: str
    kind: str
    name: str
    team_id: int
    project_name: str
    password_required: bool = False
    url: str | None = None
