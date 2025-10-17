# Products

Each product in PostHog is a **vertical slice**: it contains its backend (Django app), frontend (React/TypeScript), and optionally shared code.
This structure ensures product features are self-contained and can evolve independently.

The **entire product folder** (`products/<product_name>/`) is treated as a **Turborepo package**.
Backend and frontend are sub-parts of that package.

This is the (future) home for all PostHog products ([RFC](https://github.com/PostHog/product-internal/pull/703)).

## Folder structure

```txt
products/
  __init__.py
  <product_name>/           # Turborepo package boundary
    __init__.py             # allows imports like products.<product>.backend.*
    backend/                # Django app
      __init__.py           # marks backend as Python package/Django app
      models.py
      migrations/
      api.py
      serializers.py
      tests/                # backend tests live here
    frontend/               # frontend app
      components/
      pages/
      tests/                # frontend tests live here
    shared/                 # optional: cross-cutting code for both backend & frontend
    package.json            # defines the product package in Turborepo
    manifest.tsx            # describes the product's features
```

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
  - `manifest.tsx` - describes the product's features. All manifest files are combined into `frontend/src/products.tsx` on build.
  - `package.json` - describes the frontend dependencies. Ideally they should all be `peerDependencies` of whatever is in `frontend/package.json`
  - `__init__.py` - allows imports like `products.<product>.backend.*` (only if backend exists)
    - `backend/__init__.py` - marks the backend directory as a Python package/Django app (only if backend exists).
    - `frontend/` - React frontend code. We run prettier/eslint only on files in the `frontend` folder on commit.
    - `backend/` - Python backend code. It's treated as a separate django app.

## Adding a new product

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

## TODO

- [ ] A story for Python testing - run tests automatically, only test apps that changed, etc
