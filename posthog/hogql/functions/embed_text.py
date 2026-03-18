from posthog.hogql import ast

from posthog.api.embedding_worker import generate_embedding
from posthog.models.team.team import Team


# Takes an embed text call, calls out to the embedding worker,
# and then returns an embedding.
def resolve_embed_text(team: Team | int | None, node: ast.Call) -> ast.Constant:
    args = node.args

    if team is None:
        raise ValueError("embedText() requires a team or team ID")
    if len(args) < 1:
        raise ValueError("embedText() takes at least one argument")
    if len(args) > 2:
        raise ValueError("embedText() takes at most two arguments")

    # mypy really goes crazy
    if not isinstance(team, Team):
        team_used = Team.objects.get(id=team)
    else:
        team_used = team

    text = args[0]
    model = args[1] if len(args) == 2 else None

    if not isinstance(text, ast.Constant) or not isinstance(text.value, str):
        raise ValueError("embedText() first argument must be a string literal")
    if model is not None and (not isinstance(model, ast.Constant) or not isinstance(model.value, str)):
        raise ValueError("embedText() second argument must be a string literal")

    response = generate_embedding(team_used, text.value, model.value if model else None)

    # Return the embedding as a constant
    return ast.Constant(value=response.embedding)
