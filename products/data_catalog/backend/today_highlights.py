from products.access_control.backend.facade.user_access_control import AccessControlLevel, UserAccessControl
from products.data_catalog.backend.facade.api import PendingGroup, build_team_pending_review
from products.today.backend.facade.contracts import HighlightCandidate, HighlightContext, HighlightFindings
from products.today.backend.facade.enums import HighlightLabel

APPROVER_ACCESS_LEVEL: AccessControlLevel = "editor"
IMPORTANCE = 0.5

ONE_TITLE = "{counts} waits for approval"
MANY_TITLE = "{counts} wait for approval"
ONE_DETAIL = "Review it in the data catalog."
MANY_DETAIL = "Review them in the data catalog."


def _join(groups: list[PendingGroup]) -> str:
    counts = [f"{group.count} {group.noun}{'' if group.count == 1 else 's'}" for group in groups]
    return counts[0] if len(counts) == 1 else f"{', '.join(counts[:-1])} and {counts[-1]}"


def find_pending_approvals(context: HighlightContext) -> HighlightFindings:
    access = UserAccessControl(user=context.user, team=context.team)
    if not access.check_access_level_for_resource("data_catalog", APPROVER_ACCESS_LEVEL):
        return HighlightFindings()
    review = build_team_pending_review(context.team, sample_size=0)
    if review is None:
        return HighlightFindings()
    one = review.total == 1
    return HighlightFindings(
        items=(
            HighlightCandidate(
                key="data_catalog_approvals",
                label=HighlightLabel.OPPORTUNITY,
                family="data_catalog",
                importance=IMPORTANCE,
                relevance=1.0,
                title=(ONE_TITLE if one else MANY_TITLE).format(counts=_join(review.groups)),
                detail=ONE_DETAIL if one else MANY_DETAIL,
                url=f"/data-catalog?tab={review.groups[0].kind}",
            ),
        )
    )
