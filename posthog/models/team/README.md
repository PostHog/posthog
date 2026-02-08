# Team model and extensions

This directory contains the core `Team` model and its extension models.

## When to add fields to Team vs create an extension

**Add to Team directly** when the field is:

- Core team identity (name, API tokens, timezone)
- Cross-product settings (test account filters, path cleaning)
- SDK configuration that affects multiple products

**Create an extension** when the field is:

- Domain-specific configuration for a single product
- Part of a larger config object that grows together
- Settings that most teams won't use

Recent additions that should have been extensions include toggles for Experiments, Conversations, Session Recording, etc. Going forward, product teams should use extension models for their domain-specific configuration.

## Creating a new Team extension

```python
# posthog/models/team/team_my_product_config.py (or products/my_product/backend/models/)
import logging

from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver

from posthog.models.team import Team
from posthog.models.team.extensions import create_extension_signal_receiver

logger = logging.getLogger(__name__)


class TeamMyProductConfig(models.Model):
    # Use Team's primary key as this model's primary key
    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True)

    # Your domain-specific fields
    some_setting = models.BooleanField(default=False)
    config_json = models.JSONField(default=dict)


# Best-effort auto-creation on Team save
_create_my_product_config = create_extension_signal_receiver(
    TeamMyProductConfig,
    defaults={"some_setting": True},  # optional
    logger=logger,
)


@receiver(post_save, sender=Team)
def create_team_my_product_config(sender, instance, created, **kwargs):  # noqa: ARG001
    _create_my_product_config(sender, instance, created, **kwargs)
```

Then run `python manage.py makemigrations`.

## Usage

Access the extension directly via the helper:

```python
from posthog.models.team.extensions import get_or_create_team_extension
from .team_my_product_config import TeamMyProductConfig

config = get_or_create_team_extension(team, TeamMyProductConfig)
```

Or use `select_related` in queries to avoid N+1:

```python
teams = Team.objects.select_related('teammyproductconfig').filter(...)
for team in teams:
    config = team.teammyproductconfig  # No extra query
```
