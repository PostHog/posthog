import re

from posthog.hogql import ast
from posthog.hogql.errors import SyntaxError

# Patterns for the three command forms.
# All matching is case-insensitive.
_CREATE_RE = re.compile(
    r"^\s*CREATE\s+API\s+KEY\s+'(?P<label>[^']+)'\s+WITH\s+SCOPES\s+(?P<scopes>.+?)\s*;?\s*$",
    re.IGNORECASE,
)
_SHOW_RE = re.compile(
    r"^\s*SHOW\s+API\s+KEYS\s*;?\s*$",
    re.IGNORECASE,
)
_ALTER_RE = re.compile(
    r"^\s*ALTER\s+API\s+KEY\s+'(?P<label>[^']+)'\s+ROLL\s*;?\s*$",
    re.IGNORECASE,
)
_SCOPE_ITEM_RE = re.compile(r"'([^']+)'")


def parse_command(
    statement: str,
) -> ast.CreateApiKeyCommand | ast.ShowApiKeysCommand | ast.AlterApiKeyRollCommand:
    """Try to parse a HogQL statement as an API-key command.

    Raises SyntaxError if the statement looks like a command but is malformed.
    Raises SyntaxError if the statement is not a command at all.
    """
    stripped = statement.strip().rstrip(";").strip()
    upper = stripped.upper()

    if upper.startswith("CREATE API KEY"):
        m = _CREATE_RE.match(statement)
        if not m:
            raise SyntaxError(
                "Invalid CREATE API KEY syntax. Expected: CREATE API KEY '<label>' WITH SCOPES '<scope1>', '<scope2>'"
            )
        scopes = _SCOPE_ITEM_RE.findall(m.group("scopes"))
        if not scopes:
            raise SyntaxError("At least one scope is required")
        return ast.CreateApiKeyCommand(label=m.group("label"), scopes=scopes)

    if upper.startswith("SHOW API KEYS"):
        m = _SHOW_RE.match(statement)
        if not m:
            raise SyntaxError("Invalid SHOW API KEYS syntax. Expected: SHOW API KEYS")
        return ast.ShowApiKeysCommand()

    if upper.startswith("ALTER API KEY"):
        m = _ALTER_RE.match(statement)
        if not m:
            raise SyntaxError("Invalid ALTER API KEY syntax. Expected: ALTER API KEY '<label>' ROLL")
        return ast.AlterApiKeyRollCommand(label=m.group("label"))

    raise SyntaxError("Not a command")
