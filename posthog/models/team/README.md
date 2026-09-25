# Team model and extensions

This directory contains the core `Team` model and its extension models.

## Why this matters: availability, not just hygiene

`posthog_team` is read on virtually every request, so any `ALTER TABLE` on it — even adding a nullable column, which is metadata-only — needs an `ACCESS EXCLUSIVE` lock and can stall site-wide traffic while it waits in the lock queue behind in-flight queries. This has caused production 5xx incidents. An extension model only does a `CREATE TABLE`, which takes no lock on `posthog_team` at all.

The migration analyzer (`HotTableAlterPolicy`) blocks unacknowledged DDL on `posthog_team` in CI; fields that genuinely belong on `Team` need an entry in `posthog/management/migration_analysis/hot_table_acknowledged_migrations.txt`. See the [Altering Hot Tables](../../../docs/published/handbook/engineering/safe-django-migrations.md#altering-hot-tables) guide.

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
from django.db import models

from posthog.models.team import Team


class TeamMyProductConfig(models.Model):
    # Use Team's primary key as this model's primary key
    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True)

    # Your domain-specific fields
    some_setting = models.BooleanField(default=False)
    config_json = models.JSONField(default=dict)
```

Then run `python manage.py makemigrations`.

By default, creating a team does not create its extension rows.
A row is created on first access, through `get_or_create_team_extension`, so a team has no row until code first reads or writes that extension for it.
Put default values on the model fields, not in a `defaults=` argument at a call site, so that every path that creates the row writes the same values.
Code that reads the table outside Django (Node, Rust, raw SQL) must treat a missing row as the field defaults, for example with a `LEFT JOIN` from the team table and `COALESCE` on each field.

### Creating the row at team creation (opt-in)

Register the extension with `register_team_extension_signal` only when the row's default depends on other state at the moment the team is created, such as the organization's other teams.

```python
from posthog.models.team.extensions import register_team_extension_signal

register_team_extension_signal(TeamMyProductConfig)
```

The hook connects a `post_save` receiver on `Team` that creates the row when a team is created.
The receiver logs and ignores errors, and teams created before the registration have no row.
Django code still reads the row through `get_or_create_team_extension`, and code outside Django still treats a missing row as the field defaults.

## Usage

Access the extension via the helper — do not add accessors to the Team model:

```python
from posthog.models.team.extensions import get_or_create_team_extension
from .models.team_my_product_config import TeamMyProductConfig

config = get_or_create_team_extension(team, TeamMyProductConfig)
```

Some older extensions still have `team.<product>_config` descriptors on the Team model.
These are transitional and should not be used as a pattern for new extensions.

An extension exposed as a nested field on the team or project serializer is the exception, and does
need the descriptor.
DRF skips a `required=False` field whose attribute is missing, so removing the descriptor drops the
setting from every API response without raising.
