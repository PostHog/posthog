from antlr4 import ParserRuleContext

from posthog.hogql.errors import SyntaxException


def parse_string(text: str) -> str:
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
        raise SyntaxException(f"Invalid string literal, must start and end with the same quote type: {text}")

    # copied from clickhouse_driver/util/escape.py
    text = text.replace("\\b", "\b")
    text = text.replace("\\f", "\f")
    text = text.replace("\\r", "\r")
    text = text.replace("\\n", "\n")
    text = text.replace("\\t", "\t")
    text = text.replace("\\0", "")  # NUL characters are ignored
    text = text.replace("\\a", "\a")
    text = text.replace("\\v", "\v")
    text = text.replace("\\\\", "\\")

    return text


def parse_string_literal(ctx: ParserRuleContext) -> str:
    """Converts a STRING_LITERAL received from antlr via ctx.getText() into a Python string"""
    text = ctx.getText()
    return parse_string(text)
