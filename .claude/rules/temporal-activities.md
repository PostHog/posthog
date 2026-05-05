---
paths:
  - 'posthog/temporal/**'
  - 'products/*/backend/temporal/**'
---

# Temporal activity payload size

Temporal activity payloads have a ~2 MiB hard limit — pass large data by reference, not by value.
Activity inputs and outputs are serialized across a gRPC boundary that Temporal caps at ~2 MiB per
payload (the server rejects larger payloads via `blobSizeLimitError`).

As a conservative field-level rule, if a field could exceed ~256 KB once serialized (serialized
query results, exported file contents, LLM context, rendered HTML, image bytes, unbounded
`list[dict[str, Any]]`), write it to Postgres / S3 / object storage from _inside_ the activity and
return only the reference (row ID, S3 key). The workflow already has access to any row ID created
earlier in the same run; it does not need the content to flow back through.

Shuttling large data through the workflow on the way to persistence is a foreseeable failure mode
that produces `PayloadSizeError` (`TMPRL1103`) the moment the underlying data crosses the limit.
