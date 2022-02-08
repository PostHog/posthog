from django.db import models
from reversion.models import Revision


class RevisionTeamMetadata(models.Model):
    # A foreign key to Reversion called revision is required
    revision = models.OneToOneField(Revision, on_delete=models.CASCADE)
    team_id = models.PositiveIntegerField(null=False)
