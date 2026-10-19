"""The follow-up messages that tell a requester how the work their command started ended.

Each message names the subject with its label and link and adds a link to the result. It is built
from fixed text and values PostHog produced, never from the review text, so a pull request cannot
make the bot post its words.
"""

from products.review_hog.backend.facade.finished_review_hooks import FinishedReview
from products.stamphog.backend.facade.enums import ReviewRunStatus, ReviewVerdict
from products.stamphog.backend.facade.finished_review_hooks import FinishedReviewRun

from .follow_ups import FollowUp


def _subject(follow_up: FollowUp) -> str:
    return f"[{follow_up.subject_label}]({follow_up.subject_url})"


def review_result(finished: FinishedReview, follow_up: FollowUp) -> str:
    subject = _subject(follow_up)
    if finished.failed:
        return f"PostHog Review couldn't finish reviewing {subject}. Try `review` again in a few minutes."
    if finished.findings_count == 0:
        found = "found nothing to fix"
    elif finished.findings_count == 1:
        found = "found 1 issue"
    else:
        found = f"found {finished.findings_count} issues"
    return f"PostHog Review finished reviewing {subject} and {found}. [Open the review]({finished.review_url})"


def stamphog_result(finished: FinishedReviewRun, follow_up: FollowUp) -> str:
    subject = _subject(follow_up)
    if finished.status == ReviewRunStatus.FAILED:
        return f"Stamphog couldn't finish reviewing {subject}. Try `stamp` again in a few minutes."
    if finished.status == ReviewRunStatus.GATED:
        return f"Stamphog can't approve {subject} on its own, so it needs a person to review it."
    if finished.verdict == ReviewVerdict.APPROVED:
        return f"Stamphog approved {subject}."
    if finished.verdict == ReviewVerdict.REFUSED:
        return f"Stamphog didn't approve {subject}. Its review on the pull request says why."
    if finished.verdict == ReviewVerdict.ESCALATE:
        return f"Stamphog wants a person to review {subject}. Its review on the pull request says why."
    if finished.verdict == ReviewVerdict.WAIT:
        return f"Stamphog is waiting before it decides on {subject}. Its review on the pull request says what for."
    return f"Stamphog finished reviewing {subject}. Its review is on the pull request."


def qa_result(status: str, task_url: str, follow_up: FollowUp) -> str:
    subject = _subject(follow_up)
    run = f"[Open the run in PostHog Code]({task_url})"
    if status == "completed":
        return f"The QA run on {subject} finished, and its report is on the pull request. {run}"
    if status == "cancelled":
        return f"The QA run on {subject} was cancelled. {run}"
    return f"The QA run on {subject} failed. {run}"
