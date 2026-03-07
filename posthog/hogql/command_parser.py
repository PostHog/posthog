import re
from typing import Union

from posthog.hogql import ast
from posthog.hogql.errors import SyntaxError

CommandNode = Union[
    ast.CreateApiKeyCommand,
    ast.ShowApiKeysCommand,
    ast.AlterApiKeyRollCommand,
    ast.GrantCommand,
    ast.RevokeCommand,
    ast.ShowGrantsCommand,
]

# --- API key command patterns ---

_CREATE_RE = re.compile(
    r"^\s*CREATE\s+API\s+KEY\s+'(?P<label>[^']+)'\s+WITH\s+SCOPES\s+(?P<scopes>.+?)\s*;?\s*$",
    re.IGNORECASE,
)
_SHOW_API_KEYS_RE = re.compile(
    r"^\s*SHOW\s+API\s+KEYS\s*;?\s*$",
    re.IGNORECASE,
)
_ALTER_RE = re.compile(
    r"^\s*ALTER\s+API\s+KEY\s+'(?P<label>[^']+)'\s+ROLL\s*;?\s*$",
    re.IGNORECASE,
)
_SCOPE_ITEM_RE = re.compile(r"'([^']+)'")

# --- Access control command patterns ---

# GRANT <level> ON <resource> TO ROLE '<name>'
# GRANT <level> ON <resource> '<id>' TO ROLE '<name>'
# GRANT <level> ON <resource> TO USER '<email>'
# GRANT <level> ON <resource> '<id>' TO USER '<email>'
# GRANT <level> ON <resource> TO DEFAULT
# GRANT <level> ON <resource> '<id>' TO DEFAULT
_GRANT_RE = re.compile(
    r"^\s*GRANT\s+(?P<level>\w+)\s+ON\s+(?P<resource>\w+)"
    r"(?:\s+'(?P<resource_id>[^']+)')?"
    r"\s+TO\s+(?:(?P<target_type>ROLE|USER)\s+'(?P<target_name>[^']+)'|(?P<default>DEFAULT))"
    r"\s*;?\s*$",
    re.IGNORECASE,
)

# REVOKE ON <resource> FROM ROLE '<name>'
# REVOKE ON <resource> '<id>' FROM ROLE '<name>'
# REVOKE ON <resource> FROM USER '<email>'
# REVOKE ON <resource> '<id>' FROM USER '<email>'
# REVOKE ON <resource> FROM DEFAULT
# REVOKE ON <resource> '<id>' FROM DEFAULT
_REVOKE_RE = re.compile(
    r"^\s*REVOKE\s+ON\s+(?P<resource>\w+)"
    r"(?:\s+'(?P<resource_id>[^']+)')?"
    r"\s+FROM\s+(?:(?P<target_type>ROLE|USER)\s+'(?P<target_name>[^']+)'|(?P<default>DEFAULT))"
    r"\s*;?\s*$",
    re.IGNORECASE,
)

# SHOW GRANTS
# SHOW GRANTS ON <resource>
# SHOW GRANTS ON <resource> '<id>'
# SHOW GRANTS FOR ROLE '<name>'
# SHOW GRANTS FOR USER '<email>'
_SHOW_GRANTS_RE = re.compile(
    r"^\s*SHOW\s+GRANTS"
    r"(?:\s+ON\s+(?P<resource>\w+)(?:\s+'(?P<resource_id>[^']+)')?)?"
    r"(?:\s+FOR\s+(?P<filter_type>ROLE|USER)\s+'(?P<filter_name>[^']+)')?"
    r"\s*;?\s*$",
    re.IGNORECASE,
)


def parse_command(statement: str) -> CommandNode:
    """Try to parse a HogQL statement as a command.

    Raises SyntaxError if the statement looks like a command but is malformed.
    Raises SyntaxError if the statement is not a command at all.
    """
    stripped = statement.strip().rstrip(";").strip()
    upper = stripped.upper()

    # API key commands
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
        m = _SHOW_API_KEYS_RE.match(statement)
        if not m:
            raise SyntaxError("Invalid SHOW API KEYS syntax. Expected: SHOW API KEYS")
        return ast.ShowApiKeysCommand()

    if upper.startswith("ALTER API KEY"):
        m = _ALTER_RE.match(statement)
        if not m:
            raise SyntaxError("Invalid ALTER API KEY syntax. Expected: ALTER API KEY '<label>' ROLL")
        return ast.AlterApiKeyRollCommand(label=m.group("label"))

    # Access control commands
    if upper.startswith("GRANT"):
        m = _GRANT_RE.match(statement)
        if not m:
            raise SyntaxError(
                "Invalid GRANT syntax. Expected: GRANT <level> ON <resource> [<'id'>] TO {ROLE '<name>' | USER '<email>' | DEFAULT}"
            )
        target_type = "default" if m.group("default") else m.group("target_type").lower()
        target_name = m.group("target_name") if not m.group("default") else None
        return ast.GrantCommand(
            access_level=m.group("level").lower(),
            resource=m.group("resource").lower(),
            resource_id=m.group("resource_id"),
            target_type=target_type,
            target_name=target_name,
        )

    if upper.startswith("REVOKE"):
        m = _REVOKE_RE.match(statement)
        if not m:
            raise SyntaxError(
                "Invalid REVOKE syntax. Expected: REVOKE ON <resource> [<'id'>] FROM {ROLE '<name>' | USER '<email>' | DEFAULT}"
            )
        target_type = "default" if m.group("default") else m.group("target_type").lower()
        target_name = m.group("target_name") if not m.group("default") else None
        return ast.RevokeCommand(
            resource=m.group("resource").lower(),
            resource_id=m.group("resource_id"),
            target_type=target_type,
            target_name=target_name,
        )

    if upper.startswith("SHOW GRANTS"):
        m = _SHOW_GRANTS_RE.match(statement)
        if not m:
            raise SyntaxError(
                "Invalid SHOW GRANTS syntax. Expected: SHOW GRANTS [ON <resource> [<'id'>]] [FOR {ROLE '<name>' | USER '<email>'}]"
            )
        return ast.ShowGrantsCommand(
            resource=m.group("resource").lower() if m.group("resource") else None,
            resource_id=m.group("resource_id"),
            filter_type=m.group("filter_type").lower() if m.group("filter_type") else None,
            filter_name=m.group("filter_name"),
        )

    raise SyntaxError("Not a command")
