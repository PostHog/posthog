from typing import Any

from slack_sdk.errors import SlackApiError, SlackClientError
from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.web.async_slack_response import AsyncSlackResponse

from posthog.egress.slack.observability import record_slack_api_exception, record_slack_api_response


class SlackAsyncWebClient(AsyncWebClient):
    def __init__(
        self,
        token: str | None = None,
        *,
        source: str = "unknown",
        workspace_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(token=token, **kwargs)
        self._egress_source = source
        self._egress_workspace_id = workspace_id

    async def api_call(
        self,
        api_method: str,
        *,
        http_verb: str = "POST",
        files: dict | None = None,
        data: Any = None,
        params: dict | None = None,
        json: dict | None = None,
        headers: dict | None = None,
        auth: dict | None = None,
    ) -> AsyncSlackResponse:
        try:
            response = await super().api_call(
                api_method,
                http_verb=http_verb,
                files=files,
                data=data,
                params=params,
                json=json,
                headers=headers,
                auth=auth,
            )
        except SlackApiError as error:
            record_slack_api_response(
                error.response,
                source=self._egress_source,
                workspace_id=self._egress_workspace_id,
                method=http_verb,
                endpoint=api_method,
            )
            raise
        except SlackClientError:
            record_slack_api_exception(
                source=self._egress_source,
                workspace_id=self._egress_workspace_id,
                method=http_verb,
                endpoint=api_method,
            )
            raise

        record_slack_api_response(
            response,
            source=self._egress_source,
            workspace_id=self._egress_workspace_id,
            method=http_verb,
            endpoint=api_method,
        )
        return response
