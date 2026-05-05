---
paths:
  - '**/admin.py'
  - 'posthog/admin/**/*.py'
  - 'ee/admin/**/*.py'
---

# Django admin `ForeignKey` fields need explicit widget config

When adding a `ForeignKey`/`OneToOneField` to a model that's exposed in Django admin (including via
inlines attached to a _related_ admin), list the new field in `autocomplete_fields`,
`raw_id_fields`, or `readonly_fields` on **every** admin class that renders the model — otherwise
the default `<select>` widget loads the entire target table per row on each change-page render.

Prefer declaring the config on a shared base inline so per-parent variants (e.g., subclasses
differentiated by `fk_name`) inherit it automatically.
