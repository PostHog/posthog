def parse_string_literal(ctx):
    """Converts a string literal received from antlr via ctx.getText() into a Python string"""
    text = ctx.getText()
    if text.startswith("'") and text.endswith("'"):
        text = text[1:-1]
        text = text.replace("''", "'")
    elif text.startswith('"') and text.endswith('"'):
        text = text[1:-1]
        text = text.replace('""', '"')
    elif text.startswith("`") and text.endswith("`"):
        text = text[1:-1]
        text = text.replace("``", "`")
    else:
        raise ValueError(f"Invalid string literal, must start and end with the same quote symbol: {text}")

    # copied from clickhouse_driver/util/escape.py
    text = text.replace("\\b", "\b")
    text = text.replace("\\f", "\f")
    text = text.replace("\\r", "\r")
    text = text.replace("\\n", "\n")
    text = text.replace("\\t", "\t")
    text = text.replace("\\0", "\0")
    text = text.replace("\\a", "\a")
    text = text.replace("\\v", "\v")
    text = text.replace("\\'", "'")
    text = text.replace("\\\\", "\\")

    return text
