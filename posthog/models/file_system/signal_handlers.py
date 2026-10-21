from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from posthog.models.file_system.starred_products import star_default_products


@receiver(post_save, sender="ee.AccessControl")
def access_control_created(sender, instance, created, **kwargs):
    """Star the default products for a user who is granted access to a project."""
    if created and instance.organization_member and instance.resource == "project":
        user = instance.organization_member.user
        team = instance.team

        if settings.TEST:
            star_default_products(user, team)
        else:
            transaction.on_commit(lambda: star_default_products(user, team))
