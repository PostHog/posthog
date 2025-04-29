from typing import cast
import uuid
from posthog.api.routing import TeamAndOrgViewSetMixin
from rest_framework import status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response
from langchain_core.runnables import RunnableConfig

from posthog.models.user import User


class FixHogQLViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"

    def create(self, request: Request, *args, **kwargs) -> Response:
        from products.data_warehouse.backend.hogql_fixer_ai import HogQLQueryFixerTool

        query = request.data.get("query", None)
        error = request.data.get("error", "")

        if query is None:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "No query provided"},
            )

        trace_id = str(uuid.uuid4())
        user = cast(User, request.user)

        config: RunnableConfig = {
            "configurable": {
                "contextual_tools": {
                    "fix_hogql_query": {
                        "hogql_query": query,
                        "error_message": error,
                    }
                },
                "team_id": self.team_id,
                "trace_id": trace_id,
                "distinct_id": user.distinct_id,
            }
        }

        result = HogQLQueryFixerTool(_team_id=self.team_id, _context={}).invoke({}, config)

        return Response({"query": result, "trace_id": trace_id}, status=200)
