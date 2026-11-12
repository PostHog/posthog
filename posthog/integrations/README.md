# Integrations SDK

The integrations SDK is the only way to read and write `Integration` rows (`posthog/models/integration/model.py`).
The rows move to a separate credentials service soon.
The SDK is a small, closed set of operations, so only its transport changes after the move.
No operation returns a queryset, and no operation runs caller code inside the transaction of the backend.

```python
from posthog.integrations import IntegrationManager, IntegrationNotFound, IntegrationRecord
from posthog.integrations.fields import IntegrationReferenceField
```

The rules for callers are in `AGENTS.md`.

| Module               | Holds                                                                      |
| -------------------- | -------------------------------------------------------------------------- |
| `__init__.py`        | The public names                                                           |
| `accessors.py`       | The operations and their scope rules                                       |
| `backend/`           | The storage backends: `StorageBackend`, `DjangoBackend`, `FakeBackend`     |
| `testing.py`         | `fake_integrations_backend` for tests                                      |
| `catalogue.py`       | The kinds and their auth types (hand-written)                              |
| `kinds_generated.py` | One accessor class per kind, generated from the catalogue                  |
| `contracts.py`       | `IntegrationRecord`, `IntegrationPatch`, `IntegrationUsage` and the errors |
| `source_kinds.py`    | The registry of warehouse source kinds                                     |
| `usages.py`          | The registry of usage providers                                            |
| `lifecycle.py`       | The registry of the delete and saved hooks                                 |
| `fields.py`          | `IntegrationReferenceField` for DRF serializers                            |
| `references.py`      | `IntegrationReference`, the stored string form of a row reference          |

The model module imports `catalogue.py`, `contracts.py` and `enums.py`. These modules must not import the model.
`__init__.py` loads `IntegrationManager` on first use for the same reason.

## Read rows

An accessor fixes the kind, the auth type, or both. Each operation takes `team_id` first and returns rows in the scope of the accessor only.

| Accessor                                 | Rows                                                   | Operations       |
| ---------------------------------------- | ------------------------------------------------------ | ---------------- |
| `IntegrationManager.github.oauth`        | One kind with one auth type                            | Reads and writes |
| `IntegrationManager.stripe.any`          | One kind with every auth type                          | Reads and delete |
| `IntegrationManager.kinds("slack", ...)` | Several kinds, with the default auth type of each kind | Reads and delete |
| `IntegrationManager.any`                 | Every kind with every auth type                        | Reads and delete |
| `IntegrationManager.source(kind).token`  | Warehouse source rows of one kind with one auth type   | Reads and writes |
| `IntegrationManager.source(kind).any`    | Warehouse source rows of one kind with every auth type | Reads and delete |

Only `IntegrationManager.source(kind)` reads warehouse source rows (rows with `config["warehouse_source_type"]`).
The other accessors skip them, because their config has the shape of the warehouse source, not of the kind.
Code that handles every row the same way, such as the integrations list and delete API, adds them with `with_source_rows()`:

```python
IntegrationManager.any.with_source_rows().delete(team_id, integration_id)
IntegrationManager.slack.any.with_source_rows().list(team_id)
IntegrationManager.kinds("github", "stripe", auth_types="any").with_source_rows().get_many(team_id, ids)
```

Reads:

- `get(team_id, id)` returns the row, or raises `IntegrationNotFound` when the row is not in the scope.
- `get_many(team_id, ids)` returns `{id: row}` for the ids in the scope.
- `find(team_id, external_id=..., where={...})` returns the oldest matching row or `None`.
- `list(team_id, external_id=..., where={...}, newest_first=False)` and `exists(...)`.
- `find` and `exists` also take `team_ids=[...]` instead of `team_id`, for example the teams of an organization. Pass exactly one of the two. An empty `team_ids` matches no row.
- `usages(team_id, id)` returns the PostHog objects that use the row.

These reads go across teams, for example to the teams that share one GitHub installation:

- `list_by_external_id(external_id, team_ids=None)` returns the rows with this external id.
- `get_by_external_id(external_id, id)` returns the row with this id and this external id, or raises `IntegrationNotFound`.
- `count_by_external_id(external_id)` and `exists_by_external_id(external_id)`.
- `count_by_external_ids(external_ids)` returns `{external_id: count}` in one read, for a list page.

They need an accessor with a kind: on `IntegrationManager.any` they raise `ValueError`, because external ids are unique only per provider.
Do not take the first row of `list_by_external_id` without `team_ids`: the rule `github-installation-first-team` flags it for GitHub.

### List rows across teams

`list_across_teams(CrossTeamFilter(...))` is the one cross-team list operation.
Use it only for sweeps, admin and management commands, and reads for an organization (pass the team ids of the organization).
Request code that reads one team uses `list`.
In the credentials service, only the web, Celery and Temporal deployments can call it, and the service audits each row that it returns.
Like the other cross-team reads, it needs an accessor with a kind, and it keeps the scope of the accessor (kinds, auth types, warehouse source rows).

```python
from posthog.integrations import CrossTeamFilter, IntegrationManager

rows = IntegrationManager.email.any.list_across_teams(
    CrossTeamFilter(where={"verified": True}, where_in={"domain": ("example.com",)}, exclude_team_ids=(team_id,))
)
```

Every field of `CrossTeamFilter` is optional. The fields that are set combine with AND:

| Field                           | Selects the rows                                                                                            |
| ------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `team_ids`, `exclude_team_ids`  | Of these teams, or not of these teams. An empty `team_ids` selects no row.                                  |
| `created_by_ids`                | That these users created. An empty tuple selects no row.                                                    |
| `external_id`                   | With this external id.                                                                                      |
| `where={key: value}`            | Whose config key equals the value. The same rules as `find(where=...)`.                                     |
| `where_in={key: (values, ...)}` | Whose config key equals one of the values. It does not take `None`.                                         |
| `where_iexact={key: text}`      | Whose config key holds this string, ignoring case. A key can name one nested key, such as `"account.name"`. |
| `has_config_key=key`            | That have this config key, with any value.                                                                  |

Rows come back ordered by id, oldest first, or newest first with `newest_first=True`.
To read in pages, pass `limit`, and pass the last id of a page as `after_id` for the next page.
For a sweep over many rows, read in pages, so that one call does not load every row of a kind.
The operation has no count and no list of team ids: take them from the rows.

`IntegrationManager.kinds(...)` takes `auth_types`: `"default"` (the default auth type of each kind), `"any"` for every auth type, or a list of auth types.

Reads do not load the GitHub repository cache (`repository_cache`, `repository_cache_updated_at`), because the list can be large.
Read it with `get_repository_cache(team_id, id)`, which returns a `RepositoryCache`.
Store a fetch with `set_repository_cache(team_id, id, repositories=..., updated_at=...)`. Pass `repositories=None` when the list did not change, so the list is not written again.
`expire_repository_cache_by_external_id(external_id)` marks the list of every team's row with this external id as stale.

`where` compares named config keys for equality, for example `where={"region": "eu"}`.
Equality also compares the JSON type, so `where={"installation_id": "123"}` misses a row that stores the number `123`.
For a GitHub installation, use the external id, which always holds the installation id as a string: `IntegrationManager.github.oauth.find(team_id, external_id=str(installation_id))`.
It does not accept lookups (`a__b`), nested values or the keys that the SDK writes (`auth_type`, `warehouse_source_type`), and raises `UnsupportedIntegrationFilter`.
When you need more, add a named method to the SDK.

Each operation has an async form with an `a` prefix: `aget`, `alist`, `aupdate`, and so on.

## Write rows

Only an accessor with one auth type can write, because a new row has exactly one auth type.

- `create(team_id, external_id=..., config=..., sensitive_config=..., created_by_id=...)`. It raises `IntegrationConflict` when the team already has a row of the kind with this external id, of any auth type.
- `upsert(team_id, external_id, config=..., ...)` returns `(row, created)`. It replaces the config of an existing row and clears its `errors`, because a new config is a reconnect. `created_by_id=None` keeps the creator of an existing row. It raises `IntegrationConflict` when the existing row is not in the scope, for example a row with another auth type.
- `update(team_id, id, config_patch=..., config_remove=..., sensitive_config_patch=..., errors=...)` merges a patch. `errors=None` keeps the errors.
- `update_where(team_id, where={...}, patch=...)` patches every row of the team whose config matches `where`, under row locks, all or none. It returns `UpdatedRows`: the matched rows after the write, and the ids of the rows that changed.
- `update_by_external_id(external_id, patch)` patches the rows of every team that are in the scope. It writes only the rows that the patch changes, in one `bulk_update`, and returns their count. A `bulk_update` sends no `post_save` signal.
- `change_external_id(team_id, id, external_id)` gives the row another external id. It raises `IntegrationConflict` when the team already has a row of the kind with that id.

Delete rows with `delete(team_id, id)`. It raises `IntegrationInUse` with the usages when other objects use the row. Pass `ignore_usages=True` to delete it anyway.
`delete_by_external_id(external_id)` deletes the rows of every team in one transaction. Like `list_by_external_id`, it needs an accessor with a kind.
Both deletes run the delete hooks first. `create`, `upsert` and `update` run the saved hooks after the write. See "Run work on delete and write".

An OAuth accessor (`IntegrationManager.<kind>.oauth`) also refreshes access tokens:

- `refresh_access_token(team_id, id, stale_access_token=None)` locks the row, refreshes the token when it expires soon, saves the new tokens and returns the row.
  Pass the token that the provider refused as `stale_access_token`, to refresh also when it is still the stored token. An empty string matches a row without an access token.
  When another worker already stored a newer token, the row comes back without a refresh.
  The lock stops two workers from spending the same refresh token, which matters for providers that rotate refresh tokens (Resend, Jira).
  A refresh that fails does not raise: the row comes back with `errors` set.
  It raises `ValueError` for a kind that `OauthIntegration` cannot refresh.

## Rows are read-only

The SDK returns rows typed as `IntegrationRecord`, a read-only `Protocol`:
`id`, `reference`, `team_id`, `kind`, `integration_id`, `config`, `sensitive_config`, `errors`, `created_at`, `created_by_id`, `auth_type`, `display_name`, `access_token`, `refresh_token` and `can_be_managed_by_creator(user_id)`.
`config` and `sensitive_config` are `Mapping`s, so mypy rejects `row.config["x"] = 1`.
Mypy also rejects `.save()`, `.delete()`, `.refresh_from_db()`, managers and related rows such as `row.team`.
Use `row.team_id` and `row.created_by_id`, and load the team or the user from their own models.
Write with `update` or `upsert`. Read the row again with `get` after a change.
To set a foreign key to a row, set the id column: `task.github_integration_id = row.id`.

`reference` is the string form of the row reference (see "Store a reference outside a serializer"). Store it instead of `id`.

With `DjangoBackend` the rows are still model instances at runtime. `FakeBackend` returns `FrozenIntegrationRecord`s with the same reads.
A later change returns frozen records from every backend. It must first move the callers that need a model instance (for example the callers that read `row.team`) onto SDK operations.

The per-kind adapters next to the model (`SlackIntegration`, `GitHubIntegration`, `OauthIntegration`, ...) take an `IntegrationRecord`.
They write their row through the SDK with the helpers in `posthog/models/integration/row_writes.py`: `update` for a patch, and `refresh_access_token` for OAuth tokens.
After a write, an adapter holds the row that the SDK returned. Read the tokens from that row (`adapter.integration`, or the return value of `refresh_access_token()`), not from the row that you gave to the adapter.
While the rows are model instances, `keep_caller_row_current` also copies the stored values into the row that you gave to the adapter, so old callers keep working.
Some adapters still narrow the row to the model with `integration_model`, because callers outside the package read model-only attributes from `adapter.integration`.

## Storage backends

The accessors hold the scope rules: the kinds, the auth types, the warehouse source rows and the reserved config keys.
They send the storage work to one `StorageBackend` (`backend/protocol.py`), which `current_backend()` returns.
The primitives take and return plain data (`RowScope`, `RowFilter`, `CrossTeamFilter`, `NewIntegration`, `IntegrationPatch`, records), so a backend can send them over HTTP.

| Backend                       | Rows                                                                    |
| ----------------------------- | ----------------------------------------------------------------------- |
| `DjangoBackend` (the default) | The `Integration` model. The only SDK code that queries it.             |
| `ServiceBackend`              | The credentials service, over HTTP. Returns `FrozenIntegrationRecord`s. |
| `FakeBackend` (tests)         | A dict in memory. Returns `FrozenIntegrationRecord`s.                   |

`INTEGRATIONS_STORAGE_BACKEND` (`django` or `service`) chooses the backend of a deployment. No deployment uses `service` yet.

`ServiceBackend` notes:

- It signs a token for each request (`_ops_for` names the operations), with EdDSA (Ed25519). The private key comes from the file at `CREDENTIALS_SERVICE_INTEGRATIONS_SIGNING_KEY_PATH`, read once per process. `CREDENTIALS_SERVICE_URL` is the service address. A single-ref call names exactly that ref, and each token has one owner. A cross-team token has none.
- A plain read of the service returns no secrets. A team read gets the secrets of its rows from `POST /resolve`, and keeps them in memory for at most 60 seconds, never past the expiry of the access token. A write in the same process clears the entry. A write in another process can stay hidden for up to 60 seconds.
- `list_across_teams` returns rows without secrets. A read of their secrets raises `IntegrationServiceError`. Read the row with `get`.
- `change_external_id` and `refresh_access_token` raise `NotImplementedError` until the service has routes for them.
- It maps each service error code to an SDK exception. A code with no SDK exception raises `IntegrationServiceError`. A transport failure or a key service failure raises `IntegrationServiceUnavailable`.

To use the fake in a test:

```python
from posthog.integrations.testing import fake_integrations_backend

with fake_integrations_backend() as backend:
    row = backend.seed(team_id=team.id, kind="slack", external_id="T1")
    assert IntegrationManager.slack.oauth.get(team.id, row.id) == row
```

`FakeBackend` calls no provider. Pass `token_refresher` to return the patch that a token refresh stores.

To add an operation:

- When existing primitives can do it, add only the accessor method in `accessors.py`.
- When it needs a new storage step, also add the primitive to `StorageBackend` in `backend/protocol.py`, implement it in `backend/django_backend.py` and `backend/fake_backend.py`, and add a case to `test/test_backends.py`, which runs against every backend. When the service has a route for the step, add it to `backend/service_backend.py` and to the stub in `test/credentials_service_stub.py`. Otherwise skip the case for the service backend.

## Pick an auth type

Each kind supports some of three auth types, and has one default:

| Auth type     | Use it for                                                                                      |
| ------------- | ----------------------------------------------------------------------------------------------- |
| `oauth`       | A connection that the provider manages: an OAuth grant or an app installation                   |
| `token`       | One static secret: an API key, a personal access token, a bot token or a webhook secret         |
| `credentials` | Several typed-in fields: host, user and password, an access key and a secret, a service account |

Use the auth type of the rows that your code can handle.
A kind class has an attribute only for the auth types that the kind supports, so mypy rejects `IntegrationManager.github.credentials`.
Use `.any` only when your code handles every auth type of the kind the same way, for example a picker or a delete.

A row stores its auth type in `config["auth_type"]` only when it is not the default of its kind. The SDK writes that key. Do not write it yourself.

## Add a kind

1. Add the kind to `Integration.IntegrationKind` in `posthog/models/integration/model.py`.
2. Add the kind to `KINDS` in `catalogue.py`, with its default auth type and its other auth types.
3. Run `hogli build:projections --only integration-kinds` and commit `kinds_generated.py`.

Use `IntegrationKind` from `posthog.integrations` for kind values in code, not `Integration.IntegrationKind`.

The default of a kind is stored data. Do not change the default of a kind that has rows.

Warehouse source kinds are not in the catalogue. The warehouse product registers them at startup with `register_source_kinds`, and callers reach their rows through `IntegrationManager.source(kind)`.
A warehouse source row has `config["warehouse_source_type"]`. Every other accessor skips these rows unless you call `with_source_rows()`, and `IntegrationManager.source(kind)` reads only these rows.

## Metrics

`observability.py` records Prometheus metrics for every operation.
The `instrumented` decorator on each accessor method does this, so a new operation needs only the decorator.
An async form counts as the operation it calls.
No label holds a team id, an integration id, an external id or a config value.
A failure in the metric code is logged and never reaches the caller.

| Metric                                                                             | Answers                                                                 |
| ---------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| `integrations_sdk_operations_total{operation, accessor, kind, auth_type, outcome}` | Which operations, accessors, kinds and auth types callers use           |
| `integrations_sdk_operation_duration_seconds{operation, accessor, outcome}`        | How long each operation takes                                           |
| `integrations_sdk_rows_returned{operation, accessor}`                              | How many rows `list`, `get_many` and `list_by_external_id` return       |
| `integrations_sdk_rows_written_total{operation, kind}`                             | How many rows `update_by_external_id` and `delete_by_external_id` touch |
| `integrations_sdk_token_refresh_total{kind, result}`                               | How often a refresh is needed, and how often it fails                   |

- `accessor` is `named` (one kind), `any` (`IntegrationManager.any`), `kinds` (`IntegrationManager.kinds(...)`) or `source` (`IntegrationManager.source(kind)`).
- `kind` is `multi` for `any` and `kinds`.
- `auth_type` is `oauth`, `token`, `credentials` or `any`.
- `outcome` is `ok`, `not_found`, `conflict`, `in_use`, `unsupported_filter`, `unsupported_auth_type` or `error`. `error` is any other exception, which the SDK raises again unchanged.
- `result` is `fresh` (no refresh needed), `refreshed` (the token expires soon), `stale_token` (refreshed only because the caller passed the stored token) or `error` (the refresh failed).

## Report usages

A product that uses integration rows reports them from `products/<product>/backend/integration_usages.py`:

```python
def integration_usages(team_id: int, integration_id: int) -> list[IntegrationUsage]: ...
```

The SDK finds the module on the first call to `usages` or `delete`. Code outside a product calls `register_usage_provider` instead.
The product sets `IntegrationUsage.type` (for example `warehouse_source`, `workflow`, `hog_function`, `batch_export`). The integrations API names these types in its error when a delete finds usages.

## Run work on delete and write

Do not add a foreign key to `Integration` or a model signal receiver on it. They stop working when the rows leave the Django database.
Put the work in a hook. A product defines its hooks in `products/<product>/backend/integration_hooks.py`:

```python
def before_integration_delete(row: IntegrationRecord) -> None: ...
def after_integration_saved(row: IntegrationRecord, *, created: bool, config_changed: bool) -> None: ...
```

The SDK finds the module on the first delete or write. Code outside a product calls `register_delete_hook` or `register_saved_hook` from `lifecycle.py` when its module loads.

- `delete` and `delete_by_external_id` run the delete hooks before the backend deletes the rows, in one transaction of the Django database. A hook that raises rolls back the delete and the work of the other hooks.
- A delete hook does the work of a foreign key: a CASCADE deletes the rows that point at the row, and a SET_NULL clears the column. The foreign keys still exist and do the same work after the hooks, so a delete hook must be idempotent.
- Put work outside the database, such as a Celery task or an API call, in `transaction.on_commit`.
- `create`, `upsert` and `update` run the saved hooks after the write. `config_changed` is True when the write can change the config. An `update` runs the hooks also when the patch changes nothing. A saved hook that raises is logged, and the write stays.
- `update_by_external_id`, `change_external_id` and `refresh_access_token` do not run the saved hooks.
- The model signal receivers on `Integration` stay for the writers and deletes that do not use the SDK, such as a team delete. A receiver with a hook returns early when `sdk_runs_hooks()` is True, so its work happens once.

## Reference a row from a serializer

Use `IntegrationReferenceField` from `posthog.integrations.fields` instead of a `PrimaryKeyRelatedField` on `Integration`.
It reads the team from the serializer context, so a row of another team does not exist for the field.
Pass `kinds=[...]` to accept only rows of these kinds.
With `kinds`, the field accepts only the default auth type of each kind, because code that reads a kind expects its usual config shape.
Pass `auth_types=[AuthType.TOKEN]` to accept other auth types, or `auth_types="any"` to accept every auth type.
The field never accepts a warehouse source row.

## Store a reference outside a serializer

A model that points at a row without a foreign key stores the reference as a string, for example `ExternalDataSource.credentials_integration_id`.
Rows in the credentials service get a UUID id, and keep the int id of a row made before as `legacy_id`.
So the string is a decimal legacy id (`"123"`) or a lowercase hyphenated UUID.
Write it with `str(IntegrationReference.from_legacy_id(row.id))`, and read it with `IntegrationReference.parse(value)`, which raises `ValueError` for any other form.
The accessors take int ids, so pass `reference.legacy_id`. A UUID reference cannot resolve yet: treat it as "not found".

## Why direct model use fails CI

The semgrep rule `.semgrep/rules/devex/integration-model-through-sdk.yaml` finds uses of the model outside the SDK: imports of `Integration`, its managers (`objects`, `_default_manager`, `_base_manager`, also through `IntegrationRecord`), `apps.get_model` lookups of it, relation fields to it, `select_related` and `prefetch_related` on an integration relation, `integration__` lookups (as keyword arguments or as strings), `integration_set`, and `.save()` on a row.
The "Integration model ratchet" step in `.github/workflows/ci-security.yaml` compares the findings per file with `model_access_baseline.txt`.
It fails when a file has more findings than its baseline count, and also when it has fewer.
A file that semgrep reports an error for (a timeout or a parse error) is not checked for fewer findings, and `--update` keeps its count.
When you move a file to the SDK, lower its count in the baseline, or remove the line at zero.
Tests, migrations, Django admin, the model and its per-kind adapters (`posthog/models/integration/`) are outside the rule.
