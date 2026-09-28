# Test cases for user-email-writes-use-the-shared-fold rule.
# ruff: noqa: F821, E501
from posthog.helpers.email_utils import EmailNormalizer


def flagged_raw_write(user, email: str):
    # ruleid: user-email-writes-use-the-shared-fold
    user.email = email
    user.save()


def flagged_python_fold(user, email: str):
    # ruleid: user-email-writes-use-the-shared-fold
    user.email = email.lower()
    user.save()


def flagged_staged_write(user, email: str):
    # ruleid: user-email-writes-use-the-shared-fold
    user.pending_email = email
    user.save()


def ok_normalized_write(user, email: str):
    # ok: user-email-writes-use-the-shared-fold
    user.email = EmailNormalizer.normalize(email)
    user.save()


def ok_clearing_the_staged_address(user):
    # ok: user-email-writes-use-the-shared-fold
    user.pending_email = None
    user.save()


class Claims:
    def __init__(self, email: str):
        # ok: user-email-writes-use-the-shared-fold
        self.email = email
