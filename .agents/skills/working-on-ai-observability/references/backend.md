# Backend

The layer table in [`products/ai_observability/AGENTS.md`](../../../../products/ai_observability/AGENTS.md) says what each layer does and never does.
This file gives the reasons, and the rules the table does not carry.

## Layers

- **Views are thin because HTTP, Temporal, PostHog AI and MCP share the facade.** A decision made in a view is a decision the other three callers do not get.
- **A facade function takes typed parameters.** A loose dict or a mode flag makes every caller learn the function again.
- **A facade function may also return a plain id or count that the caller uses as it is.** It never returns something the view must reshape before it serves it.
- **The facade function is the unit of work.** Only it knows which steps must succeed or fail together, so the transaction boundary sits in the one place that shows what is inside it.
- **Behavior takes loaded data so that its tests need no database.** An ORM object is fine as data: read its fields, and leave relations, `.save()` and managers to the data access module.
- **Validation is behavior, and has one implementation.** A create and an update share one check. When two languages each need the same behavior, both run one shared case file under `shared/`.
- **An edge-case path lives in one module and one block.** The main path then reads as if only the common case existed.
- **A read that shows another access-controlled resource applies that resource's access level, in the data access module.** `logic/traces/review_queries.py` filters reviews and queues with `UserAccessControl`, so a viewer who cannot open a review does not see it on a trace.

## ClickHouse

- **Reads are flat HogQL in `logic/<concept>/*_queries.py`.** No product decision sits in SQL: the read stays dumb and the behavior stays testable.
- **A value that both a row and an aggregate show is one named HogQL expression.** Every read uses it, so a tile and a row cannot disagree.
- **CPU work after a read runs outside the query concurrency slot.** The facade returns a callable, and the view runs it after `presentation/query_concurrency.py` releases the slot, so a heavy build never holds the team's slot.

## Background work

- **A request becomes a job only for a slow external call, a big output or a result worth keeping.** A bounded read stays synchronous.

## Contracts and API shape

- **A read returns render-ready content.** Raw data is a separate read, on demand.
- **No parameter changes a response's shape.** OpenAPI, the generated client and MCP stay typed.
- **`$` and `$ai_` names appear only as data, never as contract fields.** The API does not leak ingestion internals.
- **Contracts that our frontend consumes are camelCase pydantic models served as they are.** This is the field-alias case that `products/architecture.md` names for `pydantic.BaseModel`. It saves a converter layer in our own code.
- **A list is a REST resource behind a thin view.** Filtering, sorting and paging are typed parameters handled in logic.
- **A list pages the way every product's lists do.** Read "How do lists page?" in [`products/architecture.md`](../../../../products/architecture.md).
- **A list request makes two ClickHouse reads: select the page, then read its rows by key.** A column that needs a third read is a sub-resource of the list, keyed by the rows' ids and loaded after the rows, so first rows never wait on a slow cell.
- **A resource with several sub-resources gets one nested viewset per sub-resource, one file each over a small shared base.** No sub-resource can forget a guard, and a reader loads only the endpoint they change.
- **Paths are nouns in a hierarchy.** A custom `@action` verb is for an operation that truly is not a resource. A read whose input cannot fit in a query string may be a `POST`, and its description says it is a read.

  | Instead of                                                         | Use                                                                             |
  | ------------------------------------------------------------------ | ------------------------------------------------------------------------------- |
  | `POST /traces/create_with_batch`                                   | `POST /traces` with a list body, or `POST /trace_batches`                       |
  | `POST /traces/<id>/add_review`                                     | `PUT /traces/<id>/review`                                                       |
  | `GET /trace_reviews?trace_id=<id>` for something a trace owns      | `GET /traces/<id>/review`                                                       |
  | `POST /evaluations/<id>/delete` or `GET /evaluations/<id>/disable` | `DELETE /evaluations/<id>`, `PATCH /evaluations/<id>` with `{"enabled": false}` |
  | `POST /datasets/<id>/get_items` to read                            | `GET /datasets/<id>/items` with query parameters                                |
  | `GET /traces/<id>?include=summary` changing the response           | `GET /traces/<id>/summary`                                                      |
  | `POST /traces/<id>/summarize` to start a job                       | `POST /traces/<id>/summary`, which returns the summary resource to poll         |
  | `200` with `{"error": ...}` in the body                            | The matching `4xx` status                                                       |
