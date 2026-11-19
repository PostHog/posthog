# Derive step_types in HogFlow.save(), not in the write service

The stored `step_types` column is derived in `HogFlow.save()` whenever `update_fields` is empty or names `actions`. This deliberately breaks from keeping write logic in `services/hog_flow_writes.py`.
Both service write paths end in `save()`, so deriving there covers everything the service would cover. It also covers writers that skip the service: the facade's test helper, management commands that call `save(update_fields=…)`, and many direct `HogFlow.objects.create` calls in tests.
If the derivation lived in the service, those rows would stay NULL, and the fallback that reads `actions` for NULL rows could never be removed.
Writes that skip `save()` (`bulk_update`, queryset `.update()` on `actions`) are flagged by a lint rule.
