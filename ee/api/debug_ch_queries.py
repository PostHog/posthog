import re
from typing import Optional

from dateutil.relativedelta import relativedelta
from django.utils.timezone import now
from loginas.utils import is_impersonated_session
from rest_framework import exceptions, viewsets
from rest_framework.response import Response

from posthog.client import sync_execute
from posthog.settings import MULTI_TENANCY
from posthog.settings.base_variables import DEBUG


class DebugCHQueries(viewsets.ViewSet):
    """
    Show recent queries for this user
    """

    def _get_path(self, query: str) -> Optional[str]:
        try:
            return re.findall(r"request:([a-zA-Z0-9-_@]+)", query)[0].replace("_", "/")
        except:
            return None

    def list(self, request):
        if not (request.user.is_staff or DEBUG or is_impersonated_session(request) or not MULTI_TENANCY):
            raise exceptions.PermissionDenied("You're not allowed to see queries.")

        response = sync_execute(
            """
            select
                query, query_start_time, exception, toInt8(type), query_duration_ms
            from system.query_log
            where
                query LIKE %(query)s and
                query_start_time > %(start_time)s and
                type != 1 and
                query not like %(not_query)s
            order by query_start_time desc
            limit 100""",
            {
                "query": f"/* user_id:{request.user.pk} %",
                "start_time": (now() - relativedelta(minutes=10)).timestamp(),
                "not_query": "%request:_api_debug_ch_queries_%",
            },
        )
        return Response(
            [
                {
                    "query": resp[0],
                    "timestamp": resp[1],
                    "exception": resp[2],
                    "type": resp[3],
                    "execution_time": resp[4],
                    "path": self._get_path(resp[0]),
                }
                for resp in response
            ]
        )
