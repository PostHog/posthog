# Plan: DataDeletionRequest — add `person_properties` removal support

## Context

`DataDeletionRequest` with `request_type=property_removal` already drops keys from `events.properties`
via a ClickHouse `JSONDropKeys` staged-copy/delete pipeline. The `events` table also carries a
`person_properties VARCHAR` column that denormalises person properties onto every event row. There is
currently no way to remove individual keys from that column. This plan adds an analogous `person_properties`
array field to the request, wires it through Django validation and the admin, and extends the Dagster
property-removal job to handle it in the same atomic shard pipeline.

Split into two PRs so Django (model + admin) can be reviewed and merged first, then Dagster reads the
new field once the column exists in production.

---

## PR 1 — Django changes

### Files to modify

**`posthog/models/data_deletion_request.py`**

1. Add `person_properties = ArrayField(CharField(max_length=1024), blank=True, default=list, help_text=...)` after the existing `properties` field.
2. Generalise `jsonhas_expr` to accept an optional `column: str = "properties"` argument so callers can build `JSONHas(person_properties, ...)` expressions:

   ```python
   def jsonhas_expr(prop: str, param_prefix: str, column: str = "properties") -> str:
       parts = prop.split(".")
       args = ", ".join(f"%({param_prefix}_{i})s" for i in range(len(parts)))
       return f"JSONHas({column}, {args})"
   ```

   Existing callers with no `column` argument are unaffected.

3. `_clean_person_removal`: add `if self.person_properties: raise ValidationError({"person_properties": "person_properties are not valid for person_removal."})` — mirrors the existing `properties` rejection.
4. No model-level validation that at least one of `properties`/`person_properties` is non-empty for `property_removal` (consistent with how `properties` is currently handled — the admin submit_view and Dagster op enforce this).

**`posthog/migrations/1169_datadeletionrequest_person_properties.py`** (new migration)

```python
migrations.AddField(
    model_name="datadeletionrequest",
    name="person_properties",
    field=ArrayField(CharField(max_length=1024), blank=True, default=list),
)
```

**`posthog/admin/admins/data_deletion_request_admin.py`**

1. `DataDeletionRequestForm`: add `person_properties = ArrayTextareaField(required=False, help_text="One property name per line. Required for property removal requests when 'properties' is empty.")`.
2. `_build_property_filter`: extend to also emit `JSONHas(person_properties, ...)` clauses (using `pp_` param prefix) ORed together with the existing `properties` clauses, so stats counts include events that carry the target key in either column.
3. `fetch_property_deletion_stats`: update the guard to `if not obj.properties and not obj.person_properties: raise ValueError(...)`.
4. `save_model`: extend the `EVENT_REMOVAL and obj.properties` branch to also clear `obj.person_properties = []`.
5. `fieldsets`: add `"person_properties"` next to `"properties"`.
6. `search_fields`: add `"person_properties"`.
7. `change_view` warning: update to `not obj.properties and not obj.person_properties`.
8. `submit_view` `missing_properties` guard: update to `not obj.properties and not obj.person_properties`.

---

## PR 2 — Dagster changes

### Files to modify

**`posthog/dags/data_deletion_requests.py`**

1. **`DeletionRequestContext`**: add `person_properties: list[str] = field(default_factory=list)`.

2. **New helper functions** (keeping existing `properties` helpers intact to avoid risk):

   ```python
   def _person_property_filter_clause(person_properties: list[str]) -> str:
       # like _property_filter_clause but uses jsonhas_expr(..., column="person_properties")
       # and "pp_" prefix

   def _person_property_filter_params(person_properties: list[str]) -> dict:
       # like _property_filter_params but uses "pp_" prefix
   ```

3. **`_base_params`**: include `**_person_property_filter_params(ctx.person_properties)` when non-empty.

4. **`_get_affected_mat_columns`**: add `table_column: str = "properties"` parameter; change the filter from `details.table_column == "properties"` to `details.table_column == table_column`. Existing callers are unaffected (default unchanged).

5. **`_property_removal_where`**: add `person_mat_cols: list[tuple[str, bool]] | None = None` parameter. Presence clauses build:
   - `_property_filter_clause(ctx.properties)` if `ctx.properties`
   - `_mat_col_presence_clauses(mat_cols)` if `mat_cols`
   - `_person_property_filter_clause(ctx.person_properties)` if `ctx.person_properties`
   - `_mat_col_presence_clauses(person_mat_cols)` if `person_mat_cols`

   All ORed together.

6. **`load_property_removal_request`**:
   - Load `request.person_properties` and pass into `DeletionRequestContext`.
   - Update the guard: `if not request.properties and not request.person_properties: raise dagster.Failure(...)`.
   - Add `"person_properties"` to the logged metadata.

7. **`process_property_removal_per_shard`** — inside `process_shard`:
   - Call `_get_affected_mat_columns(..., table_column="properties")` for `properties`.
   - Call `_get_affected_mat_columns(..., table_column="person_properties")` for `person_properties` (empty list → no mat cols).
   - Pass both sets to `_property_removal_where` as `mat_cols=` / `person_mat_cols=`.
   - Mutation `update_parts`: conditionally add `properties = JSONDropKeys(%(keys)s)(properties)` and/or `person_properties = JSONDropKeys(%(person_keys)s)(person_properties)` based on which lists are non-empty. Reset mat cols from both sets in the same `UPDATE` statement.
   - Verify step: build `verify_clauses` covering both columns and their mat cols.

**`posthog/dags/tests/test_data_deletion_requests.py`**

Add three tests:

- `test_load_property_removal_request_rejects_empty_both_properties`: both `properties=[]` and `person_properties=[]` → `dagster.Failure`.
- `test_full_job_person_property_removal`: insert events with a key in `person_properties`, run job, assert key removed from `person_properties` but event still exists.
- `test_full_job_both_properties_and_person_properties`: request specifies both; both columns cleaned in one run.

---

## Verification

1. Run Dagster tests: `hogli test posthog/dags/tests/test_data_deletion_requests.py`
2. Run admin tests: `hogli test posthog/admin/`
3. Verify migration applies cleanly: `python manage.py migrate --check`
