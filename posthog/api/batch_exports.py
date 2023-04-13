from asgiref.sync import async_to_sync
from django.conf import settings
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.tempora.workflows import WORKFLOWS
from posthog.temporal.client import connect


class BatchExportsView(APIView):
    """Manage BatchExports."""

    @async_to_sync
    async def get(self, request: Request, team_id: int, batch_export_id: str | None):
        """Get one or more batch exports."""

        export_types = ",".join(workflow for workflow in WORKFLOWS if "export" in workflow.get_name())
        query = f"TeamId = {team_id} and WorkflowType IN ({export_types})"

        _from, to = request.query_params.get("from"), request.query_params.get("to")

        if batch_export_id:
            query += f" and WorkflowId = '{batch_export_id}'"

        if _from:
            query += f" and StartTime >= '{_from}"
        if to:
            query += f" and StartTime < '{to}"

        client = await connect(
            settings.TEMPORAL_SCHEDULER_HOST, settings.TEMPORAL_SCHEDULER_PORT, settings.TEMPORAL_NAMESPACE
        )
        workflows = await client.list_workflows(query=query)

        response_data = {
            "total_count": 0,
            "batch_exports": [],
        }
        for workflow in workflows:
            batch_export = {
                "batch_export_id": workflow["id"],
                "execution_time": workflow["execution_time"],
                "status": workflow["status"],
            }

            response_data["batch_exports"].append(batch_export)
            response_data["total_count"] += 1

        return Response(response_data)
