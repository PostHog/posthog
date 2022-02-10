from django.db import models
from reversion.models import Revision


class RevisionTeamMetadata(models.Model):
    """
    This model hooks into the mechanism that the reversion library provides for storing additional data.
    See reversion.add_meta(model, **values) in https://django-reversion.readthedocs.io/en/stable/api.html#revision-api

    It allows us to associate each revision with a team
    """

    # A foreign key to Reversion called revision is required
    revision = models.OneToOneField(Revision, on_delete=models.CASCADE)
    team_id = models.PositiveIntegerField(null=False)
