from typing import TYPE_CHECKING

from posthog.hogql import ast
from posthog.hogql.errors import QueryError

if TYPE_CHECKING:
    from posthog.models.team.team import Team


# Takes an embed text call, calls out to the embedding worker,
# and then returns an embedding.
def resolve_embed_text(team: "Team | int | None", node: ast.Call) -> ast.Constant:
    # Lazy imports keep the embedding worker (API layer) and Django ORM off this module's import path.
    from posthog.api.embedding_worker import generate_embedding  # noqa: PLC0415
    from posthog.models.team.team import Team  # noqa: PLC0415

    from products.error_tracking.backend.indexed_embedding import EMBEDDING_TABLES  # noqa: PLC0415

    args = node.args

    if team is None:
        raise QueryError("embedText() requires a team or team ID", node=node)
    if len(args) < 1:
        raise QueryError("embedText() takes at least one argument", node=node)
    if len(args) > 2:
        raise QueryError("embedText() takes at most two arguments", node=node)

    # mypy really goes crazy
    if not isinstance(team, Team):
        team_used = Team.objects.get(id=team)
    else:
        team_used = team

    text = args[0]
    model = args[1] if len(args) == 2 else None

    if not isinstance(text, ast.Constant) or not isinstance(text.value, str):
        raise QueryError("embedText() first argument must be a string literal", node=node)
    if model is not None and (not isinstance(model, ast.Constant) or not isinstance(model.value, str)):
        raise QueryError("embedText() second argument must be a string literal", node=node)

    valid_models = sorted({table.model_name for table in EMBEDDING_TABLES})
    if model is None or model.value not in valid_models:
        raise QueryError(
            f"embedText() requires a valid model as its second argument. Valid models are: {', '.join(valid_models)}",
            node=node,
        )

    response = generate_embedding(team_used, text.value, model.value)

    # Return the embedding as a constant
    return ast.Constant(value=response.embedding)
