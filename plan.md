# Plan: HogQL API key management commands

## Goal

Add DDL-like commands to HogQL for managing personal API keys:

```sql
-- Create a new key (returns the secret value, shown only once)
CREATE API KEY 'my-key-name' WITH SCOPES 'query:read', 'insight:write'

-- List all keys for the current user
SHOW API KEYS

-- Roll (rotate) an existing key's secret value
ALTER API KEY 'my-key-name' ROLL
```

## Feasibility assessment

**Verdict: feasible, and best done at the HogQL grammar/parser level.**

### Why grammar-level is the right approach

1. The HogQL grammar (`HogQLParser.g4`) already has separate entry points
   for different statement types (`select`, `program`, `expression`).
   Adding a new top-level `command` rule is a natural extension.
2. The parser already has the `KEY` token in `HogQLLexer.common.g4`.
3. SQL-like syntax keeps it discoverable —
   the parser validates structure and we get typed AST nodes.
4. Intercepting before the parser (string matching) would be fragile.

### Why it needs a separate execution path

The `HogQLQueryRunner` pipeline goes:
parse → resolve → print SQL → send to ClickHouse.
These commands don't touch ClickHouse —
they call Django/the `PersonalAPIKey` model.
So we fork after parsing.

---

## Step 0: Extract shared API key service layer

**File:** new `posthog/models/personal_api_key_service.py`

Pull the core logic out of `PersonalAPIKeySerializer` into plain functions
so both the REST API and HogQL commands can reuse it without needing a DRF request context.

```python
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.utils import generate_random_token_personal, mask_key_value

MAX_API_KEYS_PER_USER = 10

def validate_scopes(scopes: list[str], user: User) -> list[str]:
    """Validate scope strings against API_SCOPE_OBJECTS × API_SCOPE_ACTIONS.
    Raises ValueError on invalid scope."""
    ...

def create_personal_api_key(
    user: User,
    label: str,
    scopes: list[str],
    scoped_teams: list[int] | None = None,
    scoped_organizations: list[str] | None = None,
) -> tuple[PersonalAPIKey, str]:
    """Create a key and return (model, raw_value).
    raw_value is the only time the unhashed secret is available."""
    count = PersonalAPIKey.objects.filter(user=user).count()
    if count >= MAX_API_KEYS_PER_USER:
        raise ValueError(f"Limit of {MAX_API_KEYS_PER_USER} keys reached.")
    value = generate_random_token_personal()
    secure_value = hash_key_value(value)
    mask = mask_key_value(value)
    key = PersonalAPIKey.objects.create(
        user=user, label=label, secure_value=secure_value,
        mask_value=mask, scopes=scopes,
        scoped_teams=scoped_teams, scoped_organizations=scoped_organizations,
    )
    return key, value

def roll_personal_api_key(key: PersonalAPIKey) -> tuple[PersonalAPIKey, str]:
    """Roll a key's secret. Returns (updated model, new raw_value)."""
    value = generate_random_token_personal()
    key.secure_value = hash_key_value(value)
    key.mask_value = mask_key_value(value)
    key.last_rolled_at = timezone.now()
    key.save(update_fields=["secure_value", "mask_value", "last_rolled_at"])
    return key, value

def list_personal_api_keys(user: User) -> QuerySet[PersonalAPIKey]:
    """Return all keys for a user, ordered by created_at desc."""
    return PersonalAPIKey.objects.filter(user=user).order_by("-created_at")
```

Then refactor `PersonalAPIKeySerializer.create()` and `.roll()`
to delegate to these functions, so the REST API stays unchanged.

---

## Step 1: Extend the ANTLR grammar

**Files:**

- `posthog/hogql/grammar/HogQLLexer.common.g4`
- `posthog/hogql/grammar/HogQLParser.g4`

### Lexer tokens to add

```antlr
CREATE: C R E A T E;
API: A P I;
SCOPES: S C O P E S;
SHOW: S H O W;
ALTER: A L T E R;
ROLL: R O L L;
KEYS: K E Y S;
```

(`KEY`, `WITH` already exist.)

### Parser rules to add

```antlr
// New top-level entry point alongside `select`
command
    : createApiKeyStmt SEMICOLON? EOF   # CommandCreateApiKey
    | showApiKeysStmt SEMICOLON? EOF    # CommandShowApiKeys
    | alterApiKeyStmt SEMICOLON? EOF    # CommandAlterApiKey
    ;

createApiKeyStmt
    : CREATE API KEY label=STRING_LITERAL WITH SCOPES scopeList
    ;

showApiKeysStmt
    : SHOW API KEYS
    ;

alterApiKeyStmt
    : ALTER API KEY label=STRING_LITERAL ROLL
    ;

scopeList
    : STRING_LITERAL (COMMA STRING_LITERAL)*
    ;
```

Add `CREATE`, `API`, `SCOPES`, `SHOW`, `ALTER`, `ROLL`, `KEYS` to the
`keyword` rule so they remain usable as identifiers in SELECT contexts.

---

## Step 2: Regenerate the parser

- Run ANTLR code generation for the Python backend.
- The C++ backend (`hogql_parser`) will also need updates,
  but we can **defer this** — use `backend="python"` for command parsing initially.
  The C++ parser is only performance-critical for heavy SELECT queries;
  these commands are lightweight and infrequent.

---

## Step 3: Add AST nodes

**File:** `posthog/hogql/ast.py`

```python
class CreateApiKeyCommand(Expr):
    label: str
    scopes: list[str]

class ShowApiKeysCommand(Expr):
    pass

class AlterApiKeyRollCommand(Expr):
    label: str
```

These are new top-level node types. They extend `Expr` to fit the existing
AST visitor infrastructure but don't participate in SQL printing or ClickHouse resolution.

---

## Step 4: Add parser visitor logic

**File:** `posthog/hogql/parser.py`

- Add `parse_command(statement: str) -> CreateApiKeyCommand | ShowApiKeysCommand | AlterApiKeyRollCommand`.
- Uses the Python backend (calls `get_parser(statement).command()`).
- Add visitor methods in `HogQLParseTreeConverter`:

```python
def visitCommandCreateApiKey(self, ctx):
    scopes = [s.getText().strip("'") for s in ctx.createApiKeyStmt().scopeList().STRING_LITERAL()]
    return ast.CreateApiKeyCommand(label=ctx.createApiKeyStmt().STRING_LITERAL().getText().strip("'"), scopes=scopes)

def visitCommandShowApiKeys(self, ctx):
    return ast.ShowApiKeysCommand()

def visitCommandAlterApiKey(self, ctx):
    return ast.AlterApiKeyRollCommand(label=ctx.alterApiKeyStmt().STRING_LITERAL().getText().strip("'"))
```

---

## Step 5: Add command executor

**File:** new `posthog/hogql/commands.py`

```python
from posthog.hogql import ast
from posthog.models.personal_api_key_service import (
    create_personal_api_key,
    list_personal_api_keys,
    roll_personal_api_key,
    validate_scopes,
)
from posthog.schema import HogQLQueryResponse

def execute_command(
    node: ast.Expr,
    user: User,
) -> HogQLQueryResponse:
    if isinstance(node, ast.CreateApiKeyCommand):
        validate_scopes(node.scopes, user)
        key, raw_value = create_personal_api_key(user, node.label, node.scopes)
        return HogQLQueryResponse(
            results=[[raw_value, key.label, key.scopes, str(key.created_at)]],
            columns=["api_key", "label", "scopes", "created_at"],
            types=["String", "String", "Array(String)", "DateTime"],
        )

    if isinstance(node, ast.ShowApiKeysCommand):
        keys = list_personal_api_keys(user)
        rows = [[k.id, k.label, k.mask_value, k.scopes or ["*"],
                  str(k.created_at), str(k.last_used_at), str(k.last_rolled_at)]
                for k in keys]
        return HogQLQueryResponse(
            results=rows,
            columns=["id", "label", "mask_value", "scopes",
                      "created_at", "last_used_at", "last_rolled_at"],
            types=["String", "String", "String", "Array(String)",
                   "DateTime", "DateTime", "DateTime"],
        )

    if isinstance(node, ast.AlterApiKeyRollCommand):
        key_qs = PersonalAPIKey.objects.filter(user=user, label=node.label)
        key = key_qs.first()
        if not key:
            raise ValueError(f"API key '{node.label}' not found")
        key, raw_value = roll_personal_api_key(key)
        return HogQLQueryResponse(
            results=[[raw_value, key.label, str(key.last_rolled_at)]],
            columns=["api_key", "label", "last_rolled_at"],
            types=["String", "String", "DateTime"],
        )
```

---

## Step 6: Wire into the query API

**File:** `posthog/hogql_queries/hogql_query_runner.py` or `posthog/api/query.py`

**Recommended approach — detect at the QueryViewSet level:**

Before dispatching a `HogQLQuery` to `HogQLQueryRunner`,
attempt to parse the query string as a command:

```python
from posthog.hogql.parser import parse_command
from posthog.hogql.commands import execute_command

# In the query dispatch path:
try:
    command_node = parse_command(query_string)
    return execute_command(command_node, request.user)
except SyntaxError:
    pass  # Not a command, fall through to normal HogQL execution
```

This keeps ClickHouse-bound queries completely untouched.

---

## Step 7: Response format

All three commands return `HogQLQueryResponse`-shaped results
so the frontend SQL editor renders them as tables:

### `CREATE API KEY`

| api_key         | label       | scopes                           | created_at     |
| --------------- | ----------- | -------------------------------- | -------------- |
| `phx_abc123...` | my-key-name | `["query:read","insight:write"]` | 2026-03-07T... |

### `SHOW API KEYS`

| id      | label       | mask_value   | scopes           | created_at | last_used_at | last_rolled_at |
| ------- | ----------- | ------------ | ---------------- | ---------- | ------------ | -------------- |
| abc-123 | my-key-name | `phx_...xyz` | `["query:read"]` | ...        | ...          | ...            |

### `ALTER API KEY ... ROLL`

| api_key         | label       | last_rolled_at |
| --------------- | ----------- | -------------- |
| `phx_new456...` | my-key-name | 2026-03-07T... |

---

## Step 8: Tests

1. **Parser tests** — verify all three syntaxes parse to the correct AST nodes
2. **Service layer tests** — unit tests for `create_personal_api_key`, `roll_personal_api_key`, `list_personal_api_keys`
3. **Command executor tests** — verify end-to-end: parse → execute → correct response shape
4. **Validation tests** — invalid scopes, key limit, rolling a non-existent key
5. **Integration test** — via the query API endpoint (`POST /api/environments/{id}/query`)

---

## Key considerations

| Concern                 | Assessment                                                                                                                                                                                                       |
| ----------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Service layer reuse** | Core logic extracted into `personal_api_key_service.py`. Both REST serializer and HogQL commands call the same functions. No duplicate logic.                                                                    |
| **Security**            | Commands run with the authenticated user's identity. Same permission model as the existing REST API. Secret values returned only once (CREATE, ROLL).                                                            |
| **C++ parser**          | Defer — use Python backend for command parsing. These are lightweight, infrequent operations. Add C++ support later if needed.                                                                                   |
| **Scope validation**    | Shared `validate_scopes()` function reuses the same `API_SCOPE_OBJECTS × API_SCOPE_ACTIONS` checks.                                                                                                              |
| **Key limit**           | Shared `MAX_API_KEYS_PER_USER = 10` enforced in the service layer.                                                                                                                                               |
| **ALTER key lookup**    | Lookup by `label` (user-facing name). Labels aren't unique — if duplicates exist, we could either error or require the key ID. Starting with label for simplicity, can add `ALTER API KEY ID 'uuid' ROLL` later. |
| **Extensibility**       | The `command` grammar rule is a union — adding `DROP API KEY`, `DESCRIBE API KEY`, etc. is just a new alternative + AST node + executor branch.                                                                  |

## Estimated scope

- Service layer extraction + refactor serializer: ~120 lines changed
- Grammar + AST + parser: ~220 lines
- Command executor: ~100 lines
- Query API wiring: ~30 lines
- Tests: ~250 lines
- C++ parser: deferred
