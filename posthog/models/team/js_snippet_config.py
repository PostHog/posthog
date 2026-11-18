from django.db import models


class TeamJsSnippetConfig(models.Model):
    team = models.OneToOneField("posthog.Team", on_delete=models.CASCADE, primary_key=True)

    # Version pin: null = use latest, "1.358.0" = exact, "1" = major, "1.358" = minor
    js_snippet_version = models.CharField(max_length=50, null=True, blank=True, default=None)
