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
# products/my_product/backend/models/team_my_product_config.py
import logging

from django.db import models

from posthog.models.team import Team
from posthog.models.team.extensions import register_team_extension_signal

logger = logging.getLogger(__name__)


class TeamMyProductConfig(models.Model):
    # Use Team's primary key as this model's primary key
    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True)

    # Your domain-specific fields
    some_setting = models.BooleanField(default=False)
    config_json = models.JSONField(default=dict)


register_team_extension_signal(
    TeamMyProductConfig,
    defaults={"some_setting": True},  # optional
    logger=logger,
)
```

Then run `python manage.py makemigrations`.

## Usage

Access the extension via the helper — do not add accessors to the Team model:

```python
from posthog.models.team.extensions import get_or_create_team_extension
from .models.team_my_product_config import TeamMyProductConfig

config = get_or_create_team_extension(team, TeamMyProductConfig)
```

Some older extensions still have `team.<product>_config` descriptors on the Team model.
These are transitional and should not be used as a pattern for new extensions.
