from products.customer_analytics.backend.facade.membership_snapshot_contracts import (
    MembershipSnapshotInput,
    MembershipSnapshotStatus,
)
from products.customer_analytics.backend.logic import membership_snapshot_control


async def start(input: MembershipSnapshotInput) -> str:
    return await membership_snapshot_control.start_membership_snapshot(input)


async def get_status(team_id: int) -> MembershipSnapshotStatus:
    return await membership_snapshot_control.get_membership_snapshot_status(team_id)


async def resume(team_id: int) -> None:
    await membership_snapshot_control.resume_membership_snapshot(team_id)


async def cancel(team_id: int) -> None:
    await membership_snapshot_control.cancel_membership_snapshot(team_id)
