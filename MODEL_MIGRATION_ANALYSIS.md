# Model Migration Analysis

## Summary

Based on the analysis of `posthog/models/` and existing product apps, here's what needs to be migrated:

## Already Migrated ✅
- `EarlyAccessFeature` → `products/early_access_features/backend/models.py` (already exists)
- `Task*` models → `products/tasks/backend/models.py` (already exists)
- Some interviewing models → `products/user_interviews/backend/models.py` (already exists)

## Clear Migration Candidates (8 model files)

1. **`experiment.py`** → `products/experiments/backend/models.py`
   - Contains: `Experiment`, `ExperimentHoldout`, `ExperimentSavedMetric`, `ExperimentToSavedMetric`
   - Target: Need to create backend structure

2. **`web_experiment.py`** → `products/experiments/backend/models.py`
   - Contains: `WebExperiment` (proxy model)
   - Can be merged with experiment.py

3. **`link.py`** → `products/links/backend/models.py`
   - Contains: Link-related models
   - Target: `products/links/backend/` exists

4. **`messaging.py`** → `products/messaging/backend/models.py`
   - Contains: Messaging models
   - Target: `products/messaging/backend/` exists

5. **`subscription.py`** → `products/product_analytics/backend/models.py`
   - Contains: Subscription models
   - Target: Maybe product analytics

6. **`insight.py`** → `products/product_analytics/backend/models.py`
   - Contains: Insight models
   - Target: `products/product_analytics/backend/` exists

7. **`dashboard.py`** → `products/dashboards/backend/models.py`
   - Contains: Dashboard models
   - Target: Need to create `products/dashboards/backend/`

8. **`dashboard_tile.py`** → `products/dashboards/backend/models.py`
   - Contains: Dashboard tile models
   - Target: Can be merged with dashboard

9. **`batch_imports.py`** → `products/batch_exports/backend/models.py`
    - Contains: `BatchImport` models
    - Target: Just completed migration

## Models to Keep in posthog/ (Core Infrastructure)

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

## Uncertain/Complex Cases (5 files)

- `annotation.py` - Could go to product_analytics or stay core
- `comment.py` - Could go to multiple places or stay core
- `alert.py` - Could go to product_analytics or stay core
- `tag.py`/`tagged_item.py` - Cross-cutting concern, probably stay core
- `uploaded_media.py` - Cross-cutting concern, probably stay core

## Total Migration Estimate

- **Completed**: 1 model file (batch_imports)
- **Clear candidates**: 8 model files
- **Total effort**: ~9 model files need migration

Each migration involves:
1. Move model file to `products/{app}/backend/models.py`
2. Create/update Django app configuration
3. Update all imports across codebase (using refactoring tools)
4. Create state-only migrations
5. Test changes

**Time estimate**: 1-2 hours per model file = 8-16 hours total for remaining migrations.