from dataclasses import dataclass


@dataclass(frozen=True)
class SendExpirationNotificationsInput:
    dry_run: bool
    batch_size: int = 100


@dataclass
class Recording:
    session_id: str
    recording_ttl: int


@dataclass
class Team:
    team_id: int
    name: str
    ttl_days: int
    recordings: list[Recording]


@dataclass
class Organization:
    organization_id: str
    name: str
    teams: list[Team]


@dataclass
class Notification:
    user_uuid: str
    user_email: str
    user_first_name: str
    teams: list[Team]
