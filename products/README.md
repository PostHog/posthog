# Products

Each product in PostHog is a **vertical slice**: it contains its backend (Django app), frontend (React/TypeScript), and optionally shared code.
This structure ensures product features are self-contained and can evolve independently.

The **entire product folder** (`products/<product_name>/`) is treated as a **Turborepo package**.
Backend and frontend are sub-parts of that package.

This is the (future) home for all PostHog products ([RFC](https://github.com/PostHog/product-internal/pull/703)).

For the detailed architecture rationale (frozen dataclasses, facades, isolated testing), see [architecture.md](./architecture.md).

## Folder structure

```txt
products/
  __init__.py
  <product_name>/           # Turborepo package boundary
    __init__.py             # allows imports like products.<product>.backend.*
    manifest.tsx            # describes the product's features
    package.json            # defines the product package in Turborepo
    backend/                # Django app
      __init__.py
      apps.py
      models.py
      logic.py              # business logic
      migrations/
      facade/               # cross-product Python interface
        __init__.py
        api.py              # facade methods
        contracts.py        # frozen dataclasses (+ enums)
        enums.py            # optional: exported enums/shared types
      presentation/         # DRF views/serializers
        __init__.py
        views.py
        serializers.py
        urls.py
      tasks/                # Celery tasks
        __init__.py
        tasks.py
      tests/
        conftest.py
        test_*.py
    frontend/
      components/
      scenes/
      hooks/
      logics/
      generated/            # OpenAPI-generated TypeScript types
```

Use `bin/hogli product:bootstrap <name>` to scaffold a new product with this structure.

## Backend conventions

- Each `backend/` folder is a **real Django app**.

- Register it in `INSTALLED_APPS` via `AppConfig`:

  ```python
  # products/feature_flags/backend/apps.py
  from django.apps import AppConfig

  class FeatureFlagsConfig(AppConfig):
      name = "products.feature_flags.backend"
      label = "feature_flags"
      verbose_name = "Feature Flags"
  ```

- ✅ Always use the **real Python path** for imports:

  ```python
  from products.feature_flags.backend.models import FeatureFlag
  ```

- ✅ For relations, use **string app labels**:

  ```python
  class Experiment(models.Model):
      feature_flag = models.ForeignKey(
          "feature_flags.FeatureFlag",
          on_delete=models.CASCADE,
      )
  ```

- ❌ Do **not** import models from `posthog.models` or create re-exports like `products.feature_flags.models`.

This avoids circular imports and keeps migrations/app labels stable.

## Frontend conventions

- Each `frontend/` directory contains the frontend app for the product.
- It lives under the same package as the backend.
- Backend and frontend tooling can be independent (`requirements.txt` vs. `package.json`) but remain in the same Turborepo package.
- Tests for frontend code live inside `frontend/tests/`.

## Shared code

If backend and frontend need shared schemas, validators, or constants, put them in a `shared/` directory under the product.
Keep shared code minimal to avoid tight coupling.

## Product requirements

- Each high level product should have its own folder.
  - Please keep the top level folders `under_score` cased, as dashes make it hard to import files in some languages (e.g. Python).
- Each product has a few required files / folders:
  - `manifest.tsx` - describes the product's features. All manifest files are combined into `frontend/src/products.tsx` and `frontend/src/products.json` on build.
  - `package.json` - describes the frontend dependencies. Ideally they should all be `peerDependencies` of whatever is in `frontend/package.json`
  - `__init__.py` - allows imports like `products.<product>.backend.*` (only if backend exists)
    - `backend/__init__.py` - marks the backend directory as a Python package/Django app (only if backend exists).
    - `frontend/` - React frontend code. We run oxfmt/eslint only on files in the `frontend` folder on commit.
    - `backend/` - Python backend code. It's treated as a separate django app.

## Adding a new product

The easiest way is to use hogli:

```bash
bin/hogli product:bootstrap your_product_name
```

This creates the full structure with apps.py, package.json, etc.

To check your product structure follows conventions:

```bash
bin/hogli product:lint your_product_name
```

The lint command validates:

- **Presence**: `backend:test` must exist; isolated products must also have `backend:contract-check`
- **Absence**: products must NOT have `backend:contract-check` if they are not isolated or have legacy interface leaks (where core still imports internals) — turbo-discover uses this key to classify products as isolated, which causes the full Django test suite to be skipped when that product changes
- **Legacy leaks**: products with TODO legacy leak blocks in `tach.toml` show a `⚠` warning in the tach boundaries check
- **Script content** (for `backend:test`):
  - No `|| true` or `|| exit 0` — these swallow test failures in CI
  - No no-op scripts (e.g., `echo 'No backend tests'`) when `backend/` contains actual test files
  - Pytest paths referenced in the command must exist on disk and contain discoverable tests

> [!NOTE]
> To migrate a product to full isolation (facade + contracts + selective testing), use the `isolating-product-facade-contracts` skill. See [products/architecture.md](architecture.md) for the target architecture.

### Manual setup

- Create a new folder `products/your_product_name`, keep it underscore-cased.
- Create a `manifest.tsx` file
  - Describe the product's frontend `scenes`, `routes`, `urls`, file system types, and project tree (navbar) items.
  - All manifest files are combined into a single `frontend/src/products.tsx` file on build.
  - NOTE: we don't copy imports into `products.tsx`. If you add new icons, update the imports manually in `frontend/src/products.tsx`. It only needs to be done once.
  - NOTE: if you want to add a link to the old pre-project-tree navbar, do so manually in `frontend/src/layout/navigation-3000/navigationLogic.tsx`
- Create a `package.json` file:
  - Keep the package name as `@posthog/products-your-product-name`. Include `@posthog/products-` in the name.
  - Update the global `frontend/package.json`: add your new npm package under `dependencies`.
  - If your scenes are linked up with the right paths, things should just work.
  - Each scene can either export a React component as its default export, or define a `export const scene: SceneExport = { logic, component }` object to export both a logic and a component. This way the logic stays mounted when you move away from the page. This is useful if you don't want to reload everything each time the scene is loaded.
- Create `__init__.py` and `backend/__init__.py` files if your product has python backend code.
  - `__init__.py` allows imports like `products.<name>.backend.*`
  - `backend/__init__.py` marks the backend directory as a Python package / Django app.
  - Register the backend as a Django app with an `AppConfig` that sets `label = "<name>"` (not `products.<name>`).
  - Modify `posthog/settings/web.py` and add your new product under `PRODUCTS_APPS`.
  - Modify `tach.toml` and add a new block for your product. We use `tach` to track cross-dependencies between python apps.
  - Modify `posthog/api/__init__.py` and add your API routes as you normally would (e.g. `import products.early_access_features.backend.api as early_access_feature`)
  - NOTE: we will automate some of these steps in the future, but for now, please do them manually.

## Adding or moving backend models and migrations

- Create or move your backend models under the product's `backend/` folder.
- Use direct imports from the product location (e.g., `from products.experiments.backend.models import Experiment`)
- Use string-based foreign key references to avoid circular imports (e.g., `models.ForeignKey("posthog.Team", on_delete=models.CASCADE)`)
- Create a `products/your_product_name/backend/migrations` folder.
- Run `python manage.py makemigrations your_product_name -n initial_migration`
- If this is a brand-new model, you're done.
- If you're moving a model from the old `posthog/models/` folder, there are more things to do:
  - Make sure the model's `Meta` class has `db_table = 'old_table_name'` set along with `managed = True`.
  - Run `python manage.py makemigrations posthog -n remove_old_product_name`
  - The generated migrations will want to `DROP TABLE` your old model, and `CREATE TABLE` the new one. This is not what we want.
  - Instead, we want to run `migrations.SeparateDatabaseAndState` in both migrations.
  - Follow the example in `posthog/migrations/0548_migrate_early_access_features.py` and `products/early_access_features/migrations/0001_initial_migration.py`.
  - Move all operations into `state_operations = []` and keep the `database_operations = []` empty in both migrations.
  - Run and test this a few times before merging. Data loss is irreversible.

## Separate product databases

Database isolation is part of the broader product isolation architecture (see [architecture.md](./architecture.md)). Products communicate through facades and frozen dataclass contracts — never through shared ORM queries or cross-product joins. Separate databases enforce this at the infrastructure level: if your product can't reach another product's tables, you can't accidentally couple to them.

New products get their own Postgres database by default (`hogli product:bootstrap` adds a route automatically).

**Opting out:** Remove the product's entry from `products/db_routing.yaml` and everything falls back to `default`. This weakens isolation — a bad migration or traffic spike in your product can impact the entire app, and nothing prevents accidental cross-product ORM queries. Acceptable reasons to opt out: the product has no models, or it's in early prototyping and not yet following the facade pattern.

### How it works

A route in `products/db_routing.yaml` declares which app label gets its own database:

```yaml
routes:
  - app_label: visual_review
    database: visual_review
```

This automatically:

- Registers `visual_review_db_writer` and `visual_review_db_reader` as Django database aliases
- Routes all reads/writes for the `visual_review` app through `ProductDBRouter`
- Runs migrations via `bin/migrate` (calls `migrate_product_databases` management command)
- Creates the database in local Docker via the Postgres init script

Locally (`DEBUG=1`), it auto-connects to `posthog_visual_review` on localhost. In prod, the infrastructure handles env vars and connections automatically. If the env var is absent, the route is silently skipped.

### Adding a new product database

1. Add a route in `products/db_routing.yaml` (this repo)
2. Ask `#team-infrastructure` to provision the database — they'll handle the cluster, credentials, and connection plumbing

### Cross-database constraints

Postgres doesn't support foreign keys across databases. Models on a product database **must not** use `ForeignKey` to models in the main database (Team, User, etc.). Use plain integer fields instead:

```python
# Do this — plain integer, no FK constraint
team_id = models.BigIntegerField(db_index=True)

# Not this — can't reference a table in another database
team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
```

ForeignKeys between models **within the same product database** are fine.

This aligns with the facade pattern: if your product needs data from Team or User, fetch it through the facade using IDs — don't join to the table directly. Consequences:

- No `select_related`/`prefetch_related` across databases — use the facade or manual batch fetching
- No `ON DELETE CASCADE` from the main DB — handle cleanup in application code or via background tasks
- No `transaction.atomic()` spanning both databases — design for eventual consistency across boundaries

## Running tests with Turbo

Products use Turborepo for selective testing. Only tests affected by your changes run.

```bash
# Run all product tests
pnpm turbo run backend:test

# Run specific product tests
pnpm turbo run backend:test --filter=@posthog/products-visual_review

# Dry-run to see what would execute
pnpm turbo run backend:test --dry-run=json
```

See [architecture.md](./architecture.md) for how selective testing works.
