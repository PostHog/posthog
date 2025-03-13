from django.db.models import JSONField
from django.utils import timezone

from django.db import models

from posthog.models.utils import UUIDModel
from posthog.utils import generate_short_id


from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver


class Notebook(UUIDModel):
    short_id = models.CharField(max_length=12, blank=True, default=generate_short_id)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    title = models.CharField(max_length=256, blank=True, null=True)
    content: JSONField = JSONField(default=None, null=True, blank=True)
    text_content = models.TextField(blank=True, null=True)
    deleted = models.BooleanField(default=False)
    version = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, blank=True)
    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)
    last_modified_at = models.DateTimeField(default=timezone.now)
    last_modified_by = models.ForeignKey(
        "User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="modified_notebooks",
    )

    class Meta:
        unique_together = ("team", "short_id")


@receiver(post_save, sender=Notebook)
def notebook_file_system_sync(sender, instance: Notebook, created, **kwargs):
    from posthog.models.file_system import create_or_update_file, delete_file

    if instance.deleted:
        delete_file(team=instance.team, file_type="notebook", ref=str(instance.id))
    else:
        create_or_update_file(
            team=instance.team,
            base_folder="Unfiled/Notebooks",
            name=instance.title or "Untitled",
            file_type="notebook",
            ref=str(instance.id),
            href=f"/notebooks/{instance.id}",
            meta={
                "created_at": str(getattr(instance, "created_at", "")),
                "created_by": instance.created_by_id,
            },
            created_by=instance.created_by,
        )


@receiver(post_delete, sender=Notebook)
def notebook_file_system_delete(sender, instance: Notebook, **kwargs):
    from posthog.models.file_system import delete_file

    delete_file(team=instance.team, file_type="notebook", ref=str(instance.id))
