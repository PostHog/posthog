# Tracked transport and connection hosts

Every outbound call from a source must ride the tracked transport, and any credential-bearing host field
must be declared so it can't be silently retargeted. This file also covers keeping `SOURCES.md` current.

## Outbound HTTP must go through the tracked transport

Every HTTP call from `products/warehouse_sources/backend/temporal/data_imports/sources/**` must go through `make_tracked_session()` (from
`products.warehouse_sources.backend.temporal.data_imports.sources.common.http`). The tracked session attaches `team_id`, `source_type`,
`external_data_source_id`, `external_data_schema_id`, and `external_data_job_id` to every outbound request's
log line and OTel metric, and participates in opt-in sample capture.

- For raw `requests` usage: `make_tracked_session(headers=..., retry=...)` returns a `requests.Session`. Use
  `session.get/post/...` instead of the module-level `requests.get/...` shortcuts.
- For sources that already go through `rest_source.RESTClient`: it defaults to a tracked session
  automatically; no change needed.
- For vendor SDKs that accept a session/HTTP-client hook (Stripe `RequestsClient(session=...)`,
  gspread `authorize(credentials, session=...)`, BigQuery via `AuthorizedSession` + `TrackedHTTPAdapter`),
  inject one. Reference patterns live in `stripe/stripe.py`, `google_sheets/google_sheets.py`, and
  `bigquery/bigquery.py`.
- For vendor SDKs with no injection seam (today: `bingads`, `linkedin-api`'s `RestliClient`), add a
  `# nosemgrep: data-imports-http-transport-...` pragma with a one-line reason and record the source as
  `⚠️ Vendor SDK` in `SOURCES.md`.
- gRPC SDKs are **not** exempt — they have their own tracked transport (see below).

CI enforces this via `.semgrep/rules/security/data-imports-http-transport.yaml`. The rule bans direct `requests.Session()`,
`requests.<verb>(...)`, and `httpx.Client/AsyncClient/<verb>` inside `sources/**`. Type-only imports
(`from requests import Response`, `from requests.exceptions import HTTPError`) remain allowed.

## Outbound gRPC must go through the tracked gRPC transport

gRPC calls from `sources/**` ride client interceptors from
`products.warehouse_sources.backend.temporal.data_imports.sources.common.grpc`, which attach the same `JobContext` labels to logs and
OTel metrics (`data_import_grpc_*`) and feed opt-in sample capture (protobuf → scrubbed JSON). Two seams:

- For SDKs that accept an `interceptors=` list (google-ads `GoogleAdsClient.get_service(...)`), pass
  `interceptors=tracked_interceptors(host)` on **every** `get_service` call — google-ads rebuilds the channel
  per call, so the interceptors must be re-supplied each time. Reference: `google_ads/google_ads.py`.
- For SDKs that accept a `channel=` / `transport=` (BigQuery Storage Read API), build the credential-bearing
  channel, wrap it with `make_tracked_channel(channel, host=...)`, then hand it to the transport. Reference:
  `bigquery/bigquery.py:bigquery_storage_read_client`.

CI enforces this via `.semgrep/rules/security/data-imports-grpc-transport.yaml`, which bans raw `grpc.*_channel(...)`
and direct `BigQueryReadClient(...)` / `GoogleAdsClient(...)` construction inside `sources/**` (outside the
`common/grpc/` package and the two reference source files). Operators arm sample capture with
`python manage.py warehouse_sources_capture_grpc_samples enable ...`.

## Connection host fields (credential retargeting)

If your source stores a secret (API token, password) and sends it to a host that the user configures in a
**non-`host`** field, declare that field on the source class's `connection_host_fields` property (from the
base source in `common/base.py`):

```python
@property
def connection_host_fields(self) -> list[str]:
    # `okta_domain` is where the stored API token is sent; retargeting it must re-require the token.
    return ["okta_domain"]
```

The update serializer reads this list and forces the editor to re-enter the source's secrets whenever one of
these fields changes. Without it, an org member could PATCH the host field to a server they control while the
preserved (omitted) secret is reused — exfiltrating the credential. `host` and the SSH-tunnel target are
already handled separately, so only sources whose connection target lives in a differently named field (e.g.
Okta's `okta_domain`) need to override this. The default is `[]` (no extra fields).

Pair this with `_is_host_safe` (see "Outbound HTTP must go through the tracked transport" above) at both
source-create and sync time to block hosts resolving to internal/private IPs.

## Updating SOURCES.md

`products/warehouse_sources/backend/temporal/data_imports/sources/SOURCES.md` is the inventory of every registered source, its
communication method, and whether its outbound traffic is tracked. Update it as part of the same PR
whenever you:

- **Add a new source** — initially as a Scaffolded entry; move it into the Implemented table once you
  ship working sync logic.
- **Implement a previously scaffolded source** — move the row into the Implemented table and fill in
  comm method, primary library, and tracked-transport state.
- **Migrate a vendor SDK** to inject a tracked session — flip the source from `⚠️ Vendor SDK` to `✅`.
- **Switch a source's protocol** — e.g. swap REST for gRPC, add webhook support alongside the pull API,
  or move from `requests` to a vendor SDK. Update both the comm method and tracked-transport columns.

Keep the entries alphabetical within each table. The scaffolded list is one source per line (one bullet
each, also alphabetical) so adding or removing a source only touches its own line and avoids conflicts with
concurrent PRs — don't collapse it back into a comma-separated paragraph. If you add a partially-tracked
source, also append a short "Notes on partially-tracked sources" entry explaining what blocks tracking
(e.g. a vendor SDK with no session/interceptor seam).
