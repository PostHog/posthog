# Reverted #135419: migrations lost ALTER on the query_log archive tables in posthog-cloud-infra#12553,
# so this failed in dev. Kept as a no-op to preserve numbering; the column belongs in the infra managed schemas.

operations = []  # type: ignore
