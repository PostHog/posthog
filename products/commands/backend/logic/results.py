"""The follow-up messages that tell a requester how the work their command started ended.

Each message names the subject with its label and link and adds a link to the result. It is built
from fixed text and values PostHog produced, never from the review text, so a pull request cannot
make the bot post its words.
"""

from products.knowledge_writer.backend.facade.enums import MergeCheckFailure
from products.knowledge_writer.backend.facade.finished_check_hooks import FinishedDocsCheck
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


TRANSIENT_DOCS_CHECK_FAILURES = frozenset(
    {MergeCheckFailure.RETRIES_EXHAUSTED, MergeCheckFailure.ADMISSION_LOOKUP_FAILED}
)


def docs_result(finished: FinishedDocsCheck, follow_up: FollowUp) -> str:
    subject = _subject(follow_up)
    if finished.failure_reason == MergeCheckFailure.PULL_REQUEST_NOT_MERGED:
        return f"The docs check didn't run because {subject} isn't merged."
    if finished.failure_reason == MergeCheckFailure.CHECK_CAPPED:
        return f"The docs check didn't run on {subject} because this project hit its docs check limit. Try `docs` again in a few minutes."
    if finished.failure_reason in TRANSIENT_DOCS_CHECK_FAILURES:
        return f"The docs check couldn't finish on {subject}. Try `docs` again in a few minutes."
    if finished.failure_reason is not None:
        return f"The docs check couldn't run on {subject} because the knowledge writer isn't fully set up."
    docs_pull_request = (
        f"[its docs pull request]({finished.pull_request_url})"
        if finished.pull_request_url
        else "its docs pull request"
    )
    message_by_status = {
        "started": f"The docs check found docs to change for {subject}. The knowledge writer will open a docs pull request.",
        "joined": f"The docs check found docs to change for {subject}. The knowledge writer will add them to {docs_pull_request}.",
        "duplicate": f"The knowledge writer is already writing docs for {subject}.",
        "no_docs": f"The docs check found nothing in {subject} that changes the docs, so the knowledge writer won't run.",
        "shadow": f"The docs check finished on {subject}, but the knowledge writer isn't starting runs yet.",
        "capped": f"The docs check finished on {subject}, but the knowledge writer hit its run limit. Try `docs` again tomorrow.",
        "section_busy": f"The knowledge writer is already updating the docs section {subject} changes. Try `docs` again once that pull request is up.",
        "docs_in_source_repo": f"The docs pages {subject} changes live in its own repository, so update them there.",
        "unconfigured": f"The knowledge writer isn't set up, so it won't write docs for {subject}.",
    }
    return message_by_status.get(finished.status, f"The docs check finished on {subject}.")
