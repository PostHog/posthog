# AI observability agent guide

Repo-wide conventions live in [`../../AGENTS.md`](../../AGENTS.md) and the guides it links,
[`code-style.md`](../../.agents/code-style.md) and [`architecture.md`](../../.agents/architecture.md) — kea over hooks, generated
API over `api.get`, `ph_scoped_capture` in Celery, etc. Read those first.

This file is only for rules that are specific to `products/ai_observability/`
(and to the query runners in `posthog/hogql_queries/ai/`).

**If you don't know the folder yet, read [README.md](./README.md) first**
for the directory map. Skip it if you already know where things live —
it's orientation, not a rulebook.

## Update all three query runners together

`LLMTrace` and `LLMTraceEvent` are built by three parallel query runners:

- `posthog/hogql_queries/ai/trace_query_runner.py` (single trace read)
- `posthog/hogql_queries/ai/traces_query_runner.py` (list of traces)
- `posthog/hogql_queries/ai/session_query_runner.py` (traces in a session)

Each defines its own `_map_trace` and `_map_event`. None imports
from the others. Any time you add, remove, or rename a field on
`LLMTrace` or `LLMTraceEvent`, or change how an event is shaped into
any of them, **change all three runners in the same PR** and cover the
change in `posthog/hogql_queries/ai/test/`. The type checker will not
catch drift here.

The same rule applies to routing via `ai_events` vs `events`. If one
runner adopts a new code path, the others need the matching change so
single-trace, list, and session reads don't diverge.

## How we build AI observability

Part of AI observability is built in layers, and part is older.
Six principles shape the layered code.
Together they mean a person in the web UI, an agent through MCP and a script on the API all get the same capabilities and the same answers.
Each principle has a question to ask of a diff in the layered code, and the answer must be yes.
When no rule covers a case there, answer the question.

| Principle                                                      | Ask of your diff                                                                         |
| -------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| A capability has one entry point on the server.                | Could MCP, a workflow and the HTTP view all call this same function?                     |
| Behavior does no I/O and has one home.                         | Can this behavior be tested without a database, and is there one copy of it?             |
| I/O code makes no decisions.                                   | Is this query, loader or view free of decisions?                                         |
| The server decides what data means, and the client renders it. | Would an API caller get the same answer the screen shows?                                |
| Shapes are typed and stable.                                   | Does the response keep one shape for every parameter, with no `$` or `$ai_` field names? |
| New code is designed as if old code did not exist.             | If the old code vanished tomorrow, would this still be the design?                       |

## Pick one mode for each change

Look at where the code you will change lives, then pick one mode for the whole change.
A bridge is the one module in the new code that imports an old piece.

| Mode                      | When                                                                                        | What you do                                                                      |
| ------------------------- | ------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| A. Old code, as it is     | The change is a fix or an addition to a resource that lives in an old area, at any size.    | Change it there, in the style around it. Add nothing to a layered area.          |
| B. New code with a bridge | A new capability replaces old code, or needs something that lives in old code.              | Build the new side in the layers. Connect it to the old side through one bridge. |
| C. Layered code           | The code already lives in a layered area, or the capability is new and touches no old code. | Follow the layers below in full.                                                 |

| Area                                                                                                                      | Kind    |
| ------------------------------------------------------------------------------------------------------------------------- | ------- |
| `backend/presentation/`, `backend/facade/`, `backend/logic/`, `backend/temporal/`, `frontend/redesign/`                   | Layered |
| `backend/models/`, `backend/migrations/`, `backend/routes.py`, `backend/tests/`, `frontend/generated/`, `shared/`, `mcp/` | Shared  |
| `backend/api/`, every other module and package directly under `backend/`, every other directory under `frontend/`         | Old     |
| `posthog/hogql_queries/ai/`, `posthog/temporal/ai_observability/`                                                         | Old     |

- **A change is in one mode.** Old-style code never goes into a layered area, and one URL is never served from both kinds of area.
- **A new URL names a resource, in every mode.** The HTTP method is the action: `PUT /traces/<id>/review`, not `POST /traces/<id>/add_review`.
- **Behavior that already exists is called, not copied, in every mode.**
- **Moving a resource from an old area into the layers is its own PR**, with no behavior change.
- **A review holds a PR to these rules for the code it adds, moves or extracts**, not for old code it only touches.

Load `/working-on-ai-observability` before a change or a review in mode B or C.
When you cannot tell which mode applies, say so and ask.

## Where layered code goes

These layers are the repo's product architecture, applied to our use cases.
[`products/architecture.md`](../architecture.md) defines facades, contracts and presentation for every product, and [`.agents/architecture.md`](../../.agents/architecture.md) holds the repo-wide rules.
Read them when you define a contract or place a module.

| Layer               | Path                                                             | Does                                                                                                                           | Never                                                         |
| ------------------- | ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------- |
| Presentation        | `backend/presentation/views/`                                    | Parses the request, calls one facade function, serializes the contract.                                                        | Imports `logic/` or `models/`, or decides anything.           |
| Facade              | `backend/facade/api.py`, `backend/facade/contracts.py`           | One typed function per capability, returning a contract or a callable that builds one. If it writes, it opens the transaction. | Imports DRF, or returns a model or a value the view reshapes. |
| Logic, behavior     | `backend/logic/<concept>/`                                       | Classes and pure functions that take loaded data (dataclasses, contracts, ORM objects) and return data.                        | Queries, saves, follows a lazy relation, or imports DRF.      |
| Logic, data access  | `backend/logic/<concept>/*_queries.py`, `*_store.py` for a cache | Reads and writes Postgres, ClickHouse and the cache. Returns row dataclasses or loaded objects, never positional tuples.       | Holds a product decision, or opens a transaction.             |
| Postgres schema     | `backend/models/`                                                | Fields, constraints and managers scoped by team.                                                                               | Carries behavior.                                             |
| Jobs                | `backend/temporal/`                                              | Temporal workflows and activities, started by the facade.                                                                      | Is imported by a view.                                        |
| Frontend logics     | `frontend/redesign/**/*Logic.ts`                                 | Loaders, state and URL sync.                                                                                                   | Decides a label, a default, an outcome or a count.            |
| Frontend hosts      | `frontend/redesign/**/*Host.tsx`                                 | Binds a logic to components. The only place that may import an older component.                                                | Decides what data means.                                      |
| Frontend components | `frontend/redesign/**/components/`                               | Render props, with a story.                                                                                                    | Imports kea, or reshapes API data.                            |
| Frontend modules    | other `.ts` files in `frontend/redesign/`                        | Pure functions that join API data with UI state, tested directly.                                                              | Imports kea or React.                                         |

Layered tests mirror the layers: `backend/tests/logic/<concept>/`, `backend/tests/test_facade_api.py` and `backend/tests/presentation/views/`.

## Product docs go under `docs/`

Product ADRs and engineering decision records belong in
`products/ai_observability/docs/`, not at the product root.

## Custom `@action` methods need explicit scope action lists

`ScopeBasePermission` (in `posthog/permissions.py`) only resolves
`<scope_object>:read` / `<scope_object>:write` from its built-in defaults
— `read_actions = ["list", "retrieve"]` and
`write_actions = ["create", "update", "partial_update", "patch", "destroy"]`.
Any custom `@action(detail=..., methods=[...])` falls through to `None`,
which causes `APIScopePermission.has_permission` to return False with
`"This action does not support Personal API Key access"`. Every personal
API key, OAuth token, and MCP call to that endpoint 403s — even though
the ViewSet has `scope_object` set.

Two ways to fix it on a ViewSet with custom actions:

- **Per-class action lists.** Add `scope_object_read_actions` and / or
  `scope_object_write_actions` on the ViewSet, listing the custom action
  method names. Best when the actions are stable and share the
  ViewSet's scope.

  ```python
  class EvaluationConfigViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
      scope_object = "evaluation"
      scope_object_read_actions = ["list"]
      scope_object_write_actions = ["set_active_key"]
  ```

- **Per-action override.** Pass `required_scopes=[...]` to `@action(...)`.
  Best when the scope for one action diverges from the rest of the
  ViewSet (e.g. a write-shaped endpoint that's safe enough to expose
  with `:read`, like `EvaluationViewSet.test_hog`).

  ```python
  @action(detail=False, methods=["post"], required_scopes=["evaluation:read"])
  def test_hog(self, request, **kwargs): ...
  ```

When you add or rename a custom action, update one of the two — if you
forget, the new endpoint silently 403s every API-key caller. The default
test client uses `force_login` and skips the scope check, so unit tests
pass even when the production path is broken. Verify with a personal
API key (or via the MCP layer) before merging.
