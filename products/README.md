# Product Folders

This is the (future) home for all PostHog products ([RFC](https://github.com/PostHog/product-internal/pull/703)).


## Dev guidelines

- Each high level product should have its own folder.
  - Please keep the top level folders `under_score` cased, as dashes make it hard to import files in some languages (e.g. Python).
- Each product has a few required files / folders:
  - `manifest.tsx` - describes the product's features. All manifest files are combined into `frontend/src/products.tsx` on build.
  - `package.json` - describes the frontend dependencies. Ideally they should all be `peerDependencies` of whatever is in `frontend/package.json`
  - `__init__.py` - marks the directory as a python package, needed if you include the backend.
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
- Create a `__init__.py` file if your product has python backend code.
  - This is needed to mark the directory as a Python package / Django app.
  - Modify `posthog/settings/web.py` and add your new product under `PRODUCTS_APPS`.
  - Modify `tach.toml` and add a new block for your product. We use `tach` to track cross-dependencies between python apps.
  - Modify `posthog/api/__init__.py` and add your API routes as you normally would (e.g. `import products.early_access_features.backend.api as early_access_feature`)
  - NOTE: we will automate some of these steps in the future, but for now, please do them manually.

## Adding or moving backend models and migrations

- Create or move your backend models under the product's `backend/` folder.
- Import and export them under `posthog/models/__init__.py` (see `EarlyAccessFeature` for an example)
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

## TODO:

- [ ] A story for Python testing - run tests automatically, only test apps that changed, etc 