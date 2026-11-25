from social_django.models import UserSocialAuth

from posthog.dataclasses import frozen
from posthog.helpers.email_utils import EmailLookupHandler, EmailNormalizer, EmailValidationHelper
from posthog.models.id_jag_identity import IdJagIdentity
from posthog.models.organization_domain import OrganizationDomain
from posthog.models.user import User
from posthog.session.activity import revoke_other_sessions


@frozen
class UserEmailChange:
    """A change of the email that an account signs in with.

    The identities and sessions that signed in with the old email must not reach the account after
    the change, so `apply` removes them with the write. The next sign-in with the new email links the
    account again.
    """

    user: User
    new_email: str

    def is_taken(self) -> bool:
        """True when another account holds the new email, under every fold a login resolves on."""
        return (
            EmailLookupHandler.users_matching_email(self.new_email).exclude(pk=self.user.pk).exists()
            or EmailValidationHelper.user_exists_with_stripped_alias(self.new_email, exclude_user_id=self.user.pk)
            or EmailValidationHelper.user_exists_with_gmail_canonical(self.new_email, exclude_user_id=self.user.pk)
        )

    def apply(self, *, keep_session_key: str | None) -> None:
        """Writes the new email and removes the old sign-in identities and sessions. Call it in a transaction.

        Pass `keep_session_key` only when the person in that session proved that they control the new
        email.
        """
        old_domain = OrganizationDomain.objects.get_verified_for_email_address(self.user.email)
        self.user.email = EmailNormalizer.normalize(self.new_email)
        self.user.pending_email = None
        self.user.save(update_fields=["email", "pending_email"])
        UserSocialAuth.objects.filter(user=self.user).delete()
        if old_domain is not None:
            # An ID-JAG resolves a bound subject without reading the email, so a binding to an identity
            # provider of the organization that owns the old domain would still give access tokens for
            # the account. Bindings to the providers of other organizations do not depend on this email.
            IdJagIdentity.objects.filter(
                user=self.user, identity_provider_config__organization_id=old_domain.organization_id
            ).delete()
        revoke_other_sessions(self.user, keep_session_key)
