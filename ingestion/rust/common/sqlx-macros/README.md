# common-sqlx-macros

Compile-time checked `sqlx` queries over mirrored table sets.

A service that runs against either a real table or its `_tmp` mirror cannot put the table name in `sqlx::query!`, which needs one string literal. These macros take the SQL once with `{table}` placeholders and expand it into two `sqlx` macro calls, one per set, picked at runtime by a `bool`.

```rust
use common_sqlx_macros::{mirrored_query, mirrored_query_as, mirrored_query_scalar};

let rows = mirrored_query_as!(
    OpRow,
    tables.is_validation(),
    "SELECT op_id, step FROM {lifecycle_op} WHERE team_id = $1",
    team_id
    => fetch_all(&pool)
)?;
```

- `op = "name",` before the SQL tags both expansions with `/* service='<crate name>', operation='name' */`, the SQLCommenter query-tag shape pganalyze and pgcollector read. See `rust/pgcollector/docs/query-tags.md` for the key vocabulary.
- `{name}` expands to `name` for the real set and `name_tmp` for the mirror.
- `{real|mirror}` names both sides explicitly, for tables outside the suffix convention.
- `{{` and `}}` are literal braces.
- Everything after `=>` is the executor call. It sits inside the macro because each expansion has its own row type, and awaiting inside each branch is what lets them unify. The macros only work in `async` code, and `mirrored_query_as!` rows must be named structs.

Both expansions go through the offline cache, so `cargo sqlx prepare` for the using crate needs a database with both table sets.

## Extending

Each macro wraps one `sqlx` macro; adding another (for example `query_file!`) is a new `#[proc_macro]` entry point that calls `MirroredQuery::expand` with the sqlx path. The placeholder rules live in `rewrite`, which has unit tests.
