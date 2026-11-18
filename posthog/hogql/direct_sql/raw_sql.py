from functools import lru_cache
from typing import TYPE_CHECKING, cast

from sqlparse import tokens as sqlparse_tokens
from sqlparse.engine.grouping import group
from sqlparse.exceptions import SQLParseError
from sqlparse.lexer import tokenize
from sqlparse.sql import Statement, Token

from posthog.hogql.errors import ExposedHogQLError

if TYPE_CHECKING:
    from sqlglot.tokens import (
        Token as DialectToken,
        Tokenizer,
    )


@lru_cache(maxsize=16)
def _tokenizer_class(dialect: str, alternate_escapes: bool = False) -> type["Tokenizer"]:
    from sqlglot import Dialect  # noqa: PLC0415 -- load dialect grammars only for direct queries

    base = Dialect.get_or_raise(dialect).tokenizer_class
    escapes = list(base.STRING_ESCAPES)
    if alternate_escapes:
        escapes = [escape for escape in escapes if escape != "\\"] if "\\" in escapes else [*escapes, "\\"]
    tokenizer = cast(
        "type[Tokenizer]", type("DirectQueryTokenizer", (base,), {"STRING_ESCAPES": escapes, "COMMANDS": set()})
    )
    # SQLGlot also understands template comments, which database servers do not.
    tokenizer._COMMENTS = {key: value for key, value in tokenizer._COMMENTS.items() if key != "{#"}
    return tokenizer


def _lex_direct_sql(sql: str, dialect: str) -> list["DialectToken"]:
    from sqlglot.errors import TokenError  # noqa: PLC0415 -- load dialect grammars only for direct queries

    try:
        lexed = _tokenizer_class(dialect)(dialect=dialect).tokenize(sql)
        if dialect in {"postgres", "redshift", "mysql"}:
            # Connection settings can change backslash handling. Accept either interpretation
            # only when both agree on boundaries; ordinary LIKE/regex escapes still work.
            alternate = _tokenizer_class(dialect, alternate_escapes=True)(dialect=dialect).tokenize(sql)
            if [(t.start, t.end, t.token_type) for t in lexed] != [(t.start, t.end, t.token_type) for t in alternate]:
                raise ExposedHogQLError("Raw query quoting must be unambiguous for this connection.")
    except TokenError as error:
        raise ExposedHogQLError("Raw query contains invalid quoting or comments.") from error

    if dialect == "mysql" and any(
        comment.upper().startswith(("!", "M!")) for token in lexed for comment in token.comments
    ):
        raise ExposedHogQLError("Raw MySQL queries must be read-only SELECT statements.")
    return lexed


def _guard_tokens(token: "DialectToken", *, is_call: bool, is_qualified: bool, sql: str, dialect: str) -> list[Token]:
    from sqlglot.tokens import TokenType  # noqa: PLC0415 -- load dialect grammars only for direct queries

    literal_types = {
        TokenType.STRING,
        TokenType.BIT_STRING,
        TokenType.HEX_STRING,
        TokenType.BYTE_STRING,
        TokenType.NATIONAL_STRING,
        TokenType.RAW_STRING,
        TokenType.HEREDOC_STRING,
        TokenType.UNICODE_STRING,
    }
    if token.token_type == TokenType.IDENTIFIER:
        if is_call:
            return [Token(sqlparse_tokens.Name, token.text)]
        kind = sqlparse_tokens.Name if dialect == "mysql" else sqlparse_tokens.String.Symbol
        quote = "`" if dialect == "mysql" else '"'
        return [Token(kind, quote + token.text + quote)]
    if token.token_type in literal_types:
        # ANSI_QUOTES can make a double-quoted MySQL callee an identifier.
        if dialect == "mysql" and sql[token.start] == '"' and is_call:
            return [Token(sqlparse_tokens.Name, token.text)]
        return [Token(sqlparse_tokens.String.Single, "'literal'")]
    if is_qualified and token.text.replace("$", "_").isidentifier():
        return [Token(sqlparse_tokens.Name, token.text)]
    classified = list(tokenize(token.text + ("(" if is_call else "")))
    return [Token(kind, value) for kind, value in (classified[:-1] if is_call else classified)]


def _single_statement_tokens(sql: str, dialect: str) -> list["DialectToken"]:
    from sqlglot.tokens import TokenType  # noqa: PLC0415 -- load dialect grammars only for direct queries

    statement: list[DialectToken] = []
    terminated = False
    for token in _lex_direct_sql(sql, dialect):
        if token.token_type == TokenType.SEMICOLON:
            terminated = bool(statement)
        elif terminated:
            raise ExposedHogQLError("Raw queries must contain a single statement.")
        else:
            statement.append(token)
    return statement


def parse_direct_statements(sql: str, *, dialect: str) -> list[Statement]:
    """Build the guard's token tree using the connection's literal and comment rules.

    sqlparse still groups CTEs and classifies keywords, but never lexes raw literals,
    identifiers or comments. The original SQL, not this validation tree, is executed.
    """
    from sqlglot.tokens import TokenType  # noqa: PLC0415 -- load dialect grammars only for direct queries

    lexed = _single_statement_tokens(sql, dialect)
    tokens: list[Token] = []
    for index, token in enumerate(lexed):
        is_call = index + 1 < len(lexed) and lexed[index + 1].token_type == TokenType.L_PAREN
        is_qualified = (index > 0 and lexed[index - 1].token_type == TokenType.DOT) or (
            index + 1 < len(lexed) and lexed[index + 1].token_type == TokenType.DOT
        )
        tokens.extend(_guard_tokens(token, is_call=is_call, is_qualified=is_qualified, sql=sql, dialect=dialect))
        tokens.append(Token(sqlparse_tokens.Whitespace, " "))
    try:
        return [group(Statement(tokens))] if tokens else []
    except (SQLParseError, RecursionError) as error:
        raise ExposedHogQLError("Raw query is too complex to validate. Simplify the query and try again.") from error


def ensure_single_direct_statement(sql: str, *, dialect: str) -> str:
    """Reject multi-statement raw SQL.

    Raw queries run without bound parameters, so psycopg uses the simple query
    protocol, which runs every ``;``-separated statement in one round trip.
    Restricting each request to one operation keeps authorization, timeouts, and
    response accounting aligned to the statement the caller submitted. The same
    guard protects direct MySQL queries (PyMySQL additionally disables the
    MULTI_STATEMENTS client flag by default).
    """
    _single_statement_tokens(sql, dialect)
    return sql


def nestable_direct_statement(sql: str, *, dialect: str) -> str:
    """Return the single statement in `sql` as text that another query can wrap in parentheses.

    The result ends at the last token, so it carries no semicolon. A statement with an unmatched
    parenthesis is rejected: a stray `)` would close the wrapper, and the text after it would then
    run as part of the outer query.
    """
    from sqlglot.tokens import TokenType  # noqa: PLC0415 -- load dialect grammars only for direct queries

    statement = _single_statement_tokens(sql, dialect)
    if not statement:
        raise ExposedHogQLError("Raw query is empty.")
    depth = 0
    for token in statement:
        if token.token_type == TokenType.L_PAREN:
            depth += 1
        elif token.token_type == TokenType.R_PAREN:
            depth -= 1
        if depth < 0:
            break
    if depth != 0:
        raise ExposedHogQLError("Raw query has unbalanced parentheses.")
    return sql[: statement[-1].end + 1]
