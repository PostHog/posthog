from antlr4 import ParserRuleContext

from posthog.hogql.errors import SyntaxError

# Escape map derived from clickhouse_driver's escape_chars_map:
# https://github.com/mymarilyn/clickhouse-driver/blob/master/clickhouse_driver/util/escape.py#L9
_BACKSLASH_ESCAPE_MAP: dict[str, str] = {
    "b": "\b",
    "f": "\f",
    "r": "\r",
    "n": "\n",
    "t": "\t",
    "0": "",  # NUL characters are ignored
    "a": "\a",
    "v": "\v",
    "\\": "\\",
}


def replace_common_escape_characters(text: str) -> str:
    # Single-pass left-to-right scan so that an escaped backslash (\\)
    # is consumed before the next character is inspected.
    parts: list[str] = []
    i = 0
    length = len(text)
    while i < length:
        if text[i] == "\\" and i + 1 < length:
            next_char = text[i + 1]
            replacement = _BACKSLASH_ESCAPE_MAP.get(next_char)
            if replacement is not None:
                parts.append(replacement)
                i += 2
                continue
        parts.append(text[i])
        i += 1
    return "".join(parts)


def parse_string_literal_text(text: str) -> str:
    """Converts a string received from antlr via ctx.getText() into a Python string"""
    if text.startswith("'") and text.endswith("'"):
        text = text[1:-1]
        text = text.replace("''", "'")
        text = text.replace("\\'", "'")
    elif text.startswith('"') and text.endswith('"'):
        text = text[1:-1]
        text = text.replace('""', '"')
        text = text.replace('\\"', '"')
    elif text.startswith("`") and text.endswith("`"):
        text = text[1:-1]
        text = text.replace("``", "`")
        text = text.replace("\\`", "`")
    elif text.startswith("{") and text.endswith("}"):
        text = text[1:-1]
        text = text.replace("{{", "{")
        text = text.replace("\\{", "{")
    else:
        raise SyntaxError(f"Invalid string literal, must start and end with the same quote type: {text}")

    return replace_common_escape_characters(text)


def parse_string_literal_ctx(ctx: ParserRuleContext) -> str:
    """Converts a STRING_LITERAL received from antlr via ctx.getText() into a Python string"""
    text = ctx.getText()
    return parse_string_literal_text(text)


def parse_string_text_ctx(ctx: ParserRuleContext, escape_quotes=True) -> str:
    """Converts a STRING_TEXT received from antlr via ctx.getText() into a Python string"""
    text = ctx.getText()
    if escape_quotes:
        text = text.replace("''", "'")
        text = text.replace("\\'", "'")
    text = text.replace("\\{", "{")
    return replace_common_escape_characters(text)
