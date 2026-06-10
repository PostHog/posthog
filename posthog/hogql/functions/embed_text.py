from posthog.hogql import ast
from posthog.hogql.data_provider import DataProvider


# Takes an embed text call, asks the data provider for the embedding,
# and then returns it as a constant.
def resolve_embed_text(data: DataProvider, node: ast.Call) -> ast.Constant:
    args = node.args

    if len(args) < 1:
        raise ValueError("embedText() takes at least one argument")
    if len(args) > 2:
        raise ValueError("embedText() takes at most two arguments")

    text = args[0]
    model = args[1] if len(args) == 2 else None

    if not isinstance(text, ast.Constant) or not isinstance(text.value, str):
        raise ValueError("embedText() first argument must be a string literal")
    if model is not None and (not isinstance(model, ast.Constant) or not isinstance(model.value, str)):
        raise ValueError("embedText() second argument must be a string literal")

    embedding = data.embed_text(text.value, model.value if model else None)

    # Return the embedding as a constant
    return ast.Constant(value=embedding)
