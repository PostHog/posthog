from django.conf import settings
from django.db import models
from django.contrib.postgres.fields import JSONField
from django.contrib.auth.models import AbstractUser, BaseUserManager
from typing import Union, Optional, List
from django.utils.translation import ugettext_lazy as _

import secrets


def is_email_restricted_from_signup(email: str) -> bool:
    if not hasattr(settings, "RESTRICT_SIGNUPS"):
        return False

    restricted_signups: Union[str, bool] = settings.RESTRICT_SIGNUPS
    if restricted_signups is False:
        return False

    domain = email.rsplit("@", 1)[1]
    whitelisted_domains = str(settings.RESTRICT_SIGNUPS).split(",")
    if domain in whitelisted_domains:
        return False

    return True


class UserManager(BaseUserManager):
    """Define a model manager for User model with no username field."""

    use_in_migrations = True

    def _create_user(self, email: Optional[str], password: str, **extra_fields):
        """Create and save a User with the given email and password."""
        if email is None:
            raise ValueError("The given email must be set")

        email = self.normalize_email(email)
        if is_email_restricted_from_signup(email):
            raise ValueError("Can't sign up with this email")

        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save()
        return user

    def create_user(self, email, password=None, **extra_fields):
        """Create and save a regular User with the given email and password."""
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        if not settings.TEST:
            extra_fields.setdefault("distinct_id", secrets.token_urlsafe(32))
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password, **extra_fields):
        """Create and save a SuperUser with the given email and password."""
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self._create_user(email, password, **extra_fields)

def default_onboarding_dict():
    return {'active': True, 'initial': True, 'steps': {0: False, 1: False, 2: False}}
    
class User(AbstractUser):
    username = None  # type: ignore
    email = models.EmailField(_("email address"), unique=True)
    temporary_token: models.CharField = models.CharField(
        max_length=200, null=True, blank=True
    )
    distinct_id: models.CharField = models.CharField(
        max_length=200, null=True, blank=True
    )
    email_opt_in: models.BooleanField = models.BooleanField(
        default=False, null=True, blank=True
    )
    anonymize_data: models.BooleanField = models.BooleanField(
        default=False, null=True, blank=True
    )

    onboarding: JSONField = JSONField(default=default_onboarding_dict)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: List[str] = []

    objects: UserManager = UserManager()  # type: ignore
