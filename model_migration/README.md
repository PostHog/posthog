# Model Migration Tools

This folder contains tools for migrating PostHog models from `posthog/models/` to their respective product apps.

## Files

- `migrate_models.py` - Main migration script
- `migration_config.json` - Configuration file defining which models to migrate where

## Usage

From the PostHog root directory:

```bash
# Run single migration
python model_migration/migrate_models.py --single

# Run all pending migrations
python model_migration/migrate_models.py
```

## Migration Analysis

Based on the analysis of `posthog/models/` and existing product apps, here's what needs to be migrated:

### Already Migrated ✅

- `EarlyAccessFeature` → `products/early_access_features/backend/models.py` (already exists)
- `Task*` models → `products/tasks/backend/models.py` (already exists)
- Some interviewing models → `products/user_interviews/backend/models.py` (already exists)

### Current Migration Queue

1. **`batch_imports.py`** → `products/batch_exports/backend/models.py`
    - Contains: `BatchImport` models
    - Status: Ready to migrate

2. **`link.py`** → `products/links/backend/models.py`
    - Contains: Link-related models
    - Status: Ready to migrate

3. **`experiment.py` + `web_experiment.py`** → `products/experiments/backend/models.py`
    - Contains: `Experiment`, `ExperimentHoldout`, `ExperimentSavedMetric`, `ExperimentToSavedMetric`,
      `WebExperiment` (proxy)
    - Status: Ready to migrate (combine files)

4. **`messaging.py`** → `products/messaging/backend/models.py`
    - Contains: Messaging models
    - Status: Ready to migrate

5. **`dashboard.py` + `dashboard_tile.py`** → `products/dashboards/backend/models.py`
    - Contains: Dashboard and dashboard tile models
    - Status: Ready to migrate (combine files, need to create backend structure)

6. **`insight.py` + `subscription.py`** → `products/product_analytics/backend/models.py`
    - Contains: Insight and subscription models
    - Status: Ready to migrate (combine files)

### Models to Keep in posthog/ (Core Infrastructure)

- `user.py` - Core user model
- `organization.py` - Core org model
- `project.py` - Core project model
- `team.py` - Core team model (in team/ subdirectory)
- `organization_*.py` - Organization management
- `personal_api_key.py` - Auth infrastructure
- `oauth.py` - Auth infrastructure
- `instance_setting.py` - System settings
- `async_migration.py` - Migration infrastructure
- `plugin.py` - Plugin system (core)
- `integration.py` - Integration system
- `utils.py` - Shared utilities
- `signals.py` - Django signals

### Uncertain/Complex Cases

- `annotation.py` - Could go to product_analytics or stay core
- `comment.py` - Could go to multiple places or stay core
- `alert.py` - Could go to product_analytics or stay core
- `tag.py`/`tagged_item.py` - Cross-cutting concern, probably stay core
- `uploaded_media.py` - Cross-cutting concern, probably stay core

### Migration Process

Each migration involves:

1. Move model file to `products/{app}/backend/models.py`
2. Create/update Django app configuration
3. Update all imports across codebase (using refactoring tools)
4. Create state-only migrations
5. Test changes
