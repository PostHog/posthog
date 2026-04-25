# Phase: ManyRelatedField (M2M FK) traversal

This file plans the next extension of the auto-IDOR framework: catching
cross-tenant FK binding via `serializers.ManyRelatedField` (the wrapper
DRF uses when `PrimaryKeyRelatedField(many=True)` or a M2M model field
appears on a serializer).

Phase 5a covered single-FK PATCH; the implicit-id pattern extension
covers raw `<thing>_id: IntegerField()`. Neither catches M2M IDORs —
e.g., `FeatureFlagSerializer.analytics_dashboards = TeamScopedPrimaryKeyRelatedField(many=True, queryset=Dashboard.objects.all())`
or any M2M serializer field where the queryset isn't tenant-scoped.

## Threat model

A vulnerable M2M FK lets the attacker PATCH their own resource and
bind a _list_ of victim FK pks to it, leaking access via the M2M edge.
Two example shapes:

1. `analytics_dashboards`: client sends `[victim_dashboard_pk]`. If the
   serializer doesn't scope the queryset, the attacker's flag becomes
   M2M-linked to the victim's dashboard, exposing it via subsequent
   reads through the linkage.
2. `tags`: a plain `PrimaryKeyRelatedField(many=True, queryset=Tag.objects.all())`
   would let the attacker tag their resource with a victim's tag —
   typically lower-impact, but still cross-tenant data flow.

## Detection

`serializers.ManyRelatedField` exposes `.child_relation`, which is the
underlying single-item field (a `PrimaryKeyRelatedField` or subclass).
Detection is a thin wrapper around the existing logic:

```python
if isinstance(drf_field, serializers.ManyRelatedField):
    child = drf_field.child_relation
    # Reuse _classify_explicit_fk on the child, mark the result as M2M.
```

The `WritableFKField` dataclass gains a `is_many: bool = False` flag.

## Body construction

Top-level M2M PATCH body is a list:

```python
body = {fk.serializer_field_name: [str(victim_fk_pk)]}
```

For nested M2M (e.g., `destination.tags=[...]`), wrap as today:

```python
body = {fk.nested_path[0]: {fk.serializer_field_name: [str(victim_fk_pk)]}}
```

## Result verification

Different from single-FK: a PATCH body of `[victim_pk]` _replaces_ the
M2M set on the attacker's instance (DRF's default behavior). Two failure
shapes:

1. **2xx + M2M now contains victim_fk_pk** — IDOR confirmed.
2. **2xx + M2M doesn't contain victim_fk_pk** — silently dropped (some
   serializers strip unknown pks); pass.

Reload check:

```python
reloaded = case.model_cls.objects.get(pk=instance.pk)
related_manager = getattr(reloaded, fk.serializer_field_name)
linked_pks = set(related_manager.values_list("pk", flat=True))
if victim_fk_pk in linked_pks:
    raise AssertionError(...)
```

The attribute resolution may need to use `fk.source_attr` when the
M2M is exposed under a different name from its model attribute.

## Edge cases

1. **Through-tables with extra fields** — some M2Ms use `through=` with
   extra columns (e.g., `RoleMembership` on `Role.users`). DRF
   serializes these via a nested ModelSerializer rather than a
   ManyRelatedField, so today's depth-1 nested traversal already
   handles them. Document explicitly.
2. **Read-only on M2M** — same skip rule as single-FK: skip if
   `read_only=True` or in `Meta.read_only_fields`.
3. **`source=` overrides on M2M** — DRF resolves M2M source via
   `field.source_attrs`. Reuse the same source resolution as the
   implicit-id path.
4. **Empty PATCH list** — sending `[]` clears the M2M. Tests must
   restore or run on a throwaway instance to avoid order-dependence.
5. **M2M on the through model itself** — when the serializer's `Meta.model`
   is the M2M through table (e.g., `RoleMembership`), the FK on it is
   already a single-FK case. Skip from M2M discovery to avoid double
   counting.

## Implementation steps (5–6 commits)

1. **`feat(idor-tests): expose M2M FK fields via ManyRelatedField traversal`**
   - Extend `_walk_fields` to also classify `ManyRelatedField` via
     `child_relation`.
   - Add `is_many: bool = False` to `WritableFKField`.
   - Unit tests with fake serializers exposing `many=True` PK fields
     (scoped + unscoped).

2. **`feat(idor-tests): build M2M PATCH bodies in test_cross_tenant_fk_in_patch`**
   - Branch on `fk.is_many` to wrap the pk in a list.
   - Reload-and-check against the M2M manager.

3. **`feat(idor-tests): handle nested M2M one level deep`**
   - Mirror the existing nested-PK shape; rely on the same
     `nested_path` plumbing.

4. **`test(idor-tests): canary for M2M FK detection`**
   - Two fake serializers (vulnerable unscoped many=True; safe scoped).
   - Verify discovery flags the unscoped one with `is_many=True`,
     `is_already_scoped=False`.

5. **`chore(idor-tests): extend CI coverage check counts to M2M`**
   - Surface `m2m_total` separately in `check-idor-test-coverage.py`
     so we can see how many ManyRelatedField pairs got picked up.

6. **`docs(security): document M2M FK coverage`**
   - Brief note in `.agents/security.md` covering the M2M variant and
     the empty-list edge case.

## Expected delta

Surveying production: ~5–8 additional FK pairs, dominated by the
analytics_dashboards / tags style fields. Low absolute count, but high
signal — historically these have been the easiest to overlook because
the queryset only needs scoping at the _single-item_ level, which is
visually muted by the `many=True` argument.

## Out of scope (future)

- M2M with custom through-models that have additional tenant-scoped
  FKs (e.g., `RoleMembership.role` _and_ `RoleMembership.user`).
  Today depth-1 nested traversal would catch the inner FKs once the
  through-table is serialized; verify and skip if redundant.
- ManyRelatedField inside nested serializers at depth ≥2 — deferred
  alongside the deeper-nesting work in Phase 5c.
