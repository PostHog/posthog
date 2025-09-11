from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils import timezone


# DEPRECATED - DO NOT USE
class Prompt(models.Model):
    step = models.IntegerField()
    type = models.CharField(max_length=200)  # tooltip, modal, etc
    title = models.CharField(max_length=200)
    text = models.CharField(max_length=1000)
    placement = models.CharField(
        max_length=200, default="top"
    )  # top, bottom, left, right, top-start, bottom-start, etc.
    buttons = models.JSONField()
    reference = models.CharField(
        max_length=200, default=None, null=True
    )  # should match a `data-attr` reference to attach to a component
    icon = models.CharField(max_length=200)  # sync with iconMap in frontend


# DEPRECATED - DO NOT USE
class PromptSequence(models.Model):
    key = models.CharField(max_length=200)
    type = models.CharField(max_length=200)  # we use this to toggle different behaviors in the frontend
    path_match: ArrayField = ArrayField(models.CharField(max_length=200))  # wildcard path to match the current URL
    path_exclude: ArrayField = ArrayField(models.CharField(max_length=200))  # wildcard path to exclude the current URL
    status = models.CharField(max_length=200)  # active, inactive, etc
    must_have_completed = models.ManyToManyField("self", blank=True, symmetrical=False)
    requires_opt_in = models.BooleanField(default=False)
    prompts = models.ManyToManyField(Prompt)
    autorun = models.BooleanField(default=True)  # whether to run this sequence automatically for all users

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["key"], name="unique_prompt_sequence"),
        ]


# DEPRECATED - DO NOT USE
class UserPromptState(models.Model):
    user = models.ForeignKey("User", on_delete=models.CASCADE)
    sequence = models.ForeignKey(PromptSequence, on_delete=models.CASCADE)

    last_updated_at = models.DateTimeField(default=timezone.now)
    step = models.IntegerField(default=None, null=True)
    completed = models.BooleanField(default=False)
    dismissed = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "sequence"], name="unique_user_prompt_state")]
