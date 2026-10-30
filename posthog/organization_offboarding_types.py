from datetime import datetime

from posthog.dataclasses import frozen


@frozen
class OffboardingResource:
    id: str
    resource_id: str
    kind: str
    name: str
    team_id: int
    project_name: str
    created_at: datetime | None = None
    password_required: bool = False
    url: str | None = None
    destination_type: str | None = None
    destination: str | None = None
