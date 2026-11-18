# Test cases for user-email-lookups-use-the-shared-fold rule.
# ruff: noqa: F821, E501
from django.contrib.auth import get_user_model

from posthog.helpers.email_utils import EmailLookupHandler
from posthog.models import User


def flagged_exists_gate(email: str):
    # ruleid: user-email-lookups-use-the-shared-fold
    return User.objects.filter(email__iexact=email).exists()


def flagged_get(email: str):
    # ruleid: user-email-lookups-use-the-shared-fold
    return User.objects.get(email__iexact=email, is_active=True)


def flagged_on_a_queryset(queryset, email: str):
    # ruleid: user-email-lookups-use-the-shared-fold
    return queryset.filter(email__iexact=email).first()


def flagged_exact_match(email: str):
    # An exact match misses every address that folds onto the same account.
    # ruleid: user-email-lookups-use-the-shared-fold
    return User.objects.filter(email=email).first()


def flagged_swappable_model_get(email: str):
    # ruleid: user-email-lookups-use-the-shared-fold
    return get_user_model().objects.get(email__iexact=email)


def flagged_swappable_model_exact_match(email: str):
    # ruleid: user-email-lookups-use-the-shared-fold
    return get_user_model().objects.filter(email=email).first()


def ok_shared_fold_queryset(email: str):
    # ok: user-email-lookups-use-the-shared-fold
    return EmailLookupHandler.users_matching_email(email).exists()


def ok_shared_fold_single_account(email: str):
    # ok: user-email-lookups-use-the-shared-fold
    return EmailLookupHandler.get_user_by_email(email, is_active=None)


def ok_invite_lookup(organization, target_email: str):
    # ok: user-email-lookups-use-the-shared-fold
    return organization.invites.filter(target_email__iexact=target_email).first()
