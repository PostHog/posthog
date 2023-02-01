def parse_string_literal(ctx):
    text = ctx.getText()
    if text.startswith("'") and text.endswith("'"):
        text = text[1:-1]
        text = text.replace("''", "'")
    elif text.startswith('"') and text.endswith('"'):
        text = text[1:-1]
        text = text.replace('""', '"')
    else:
        raise ValueError(f"Invalid string literal, must start and end with the same quotes: {text}")

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
