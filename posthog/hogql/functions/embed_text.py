from posthog.hogql import ast

from posthog.api.embedding_worker import generate_embedding
from posthog.models.team.team import Team


# Takes an embed text call, calls out to the embedding worker,
# and then returns an embedding.
def resolve_embed_text(team_id: int, node: ast.Call) -> ast.Constant:
    args = node.args
    if len(args) < 1:
        raise ValueError("embed_text() takes at least one argument")
    if len(args) > 2:
        raise ValueError("embed_text() takes at most two arguments")

    text = args[0]
    model = args[1] if len(args) == 2 else None

    if not isinstance(text, ast.Constant) or not isinstance(text.value, str):
        raise ValueError("embed_text() first argument must be a string literal")
    if model is not None and (not isinstance(model, ast.Constant) or not isinstance(model.value, str)):
        raise ValueError("embed_text() second argument must be a string literal")

    response = generate_embedding(Team.objects.get(id=team_id), text.value, model.value if model else None)

    # Return the embedding as a constant
    return ast.Constant(value=response.embedding)
