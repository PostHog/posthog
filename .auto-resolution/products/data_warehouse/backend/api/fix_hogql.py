import uuid
from typing import cast

import posthoganalytics
from langchain_core.runnables import RunnableConfig
from posthoganalytics.ai.langchain.callbacks import CallbackHandler
from rest_framework import status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
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

        trace_id = f"fix_hogql_query_{uuid.uuid4()}"
        user = cast(User, request.user)

        config: RunnableConfig = {
            "configurable": {
                "contextual_tools": {
                    "fix_hogql_query": {
                        "hogql_query": query,
                        "error_message": error,
                    }
                },
                "team": self.team,
                "user": user,
                "trace_id": trace_id,
                "distinct_id": user.distinct_id,
            },
            "callbacks": (
                [CallbackHandler(posthoganalytics.default_client, distinct_id=user.distinct_id, trace_id=trace_id)]
                if posthoganalytics.default_client
                else None
            ),
        }

        result = HogQLQueryFixerTool(team=self.team, user=user).invoke({}, config)

        if result is None or (isinstance(result, str) and len(result) == 0):
            return Response({"trace_id": trace_id, "error": "Could not fix the query"}, status=400)

        return Response({"query": result, "trace_id": trace_id}, status=200)
