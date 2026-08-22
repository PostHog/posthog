from posthog.dataclasses import frozen


@frozen
class DispatchAccountPropertySyncInput:
    team_id: int
    saved_query_id: str
    job_id: str


@frozen
class AccountPropertySyncInput:
    team_id: int
    saved_query_id: str
    job_id: str
    segment: str
