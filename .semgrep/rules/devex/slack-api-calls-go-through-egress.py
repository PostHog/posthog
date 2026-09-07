# ruff: noqa: F841
import requests
from slack_sdk import WebClient

from posthog.egress.slack.client import SlackWebClient
from posthog.egress.slack.transport import slack_request


def flagged_literal_url(token: str):
    # ruleid: slack-api-calls-go-through-egress
    return requests.post("https://slack.com/api/chat.postMessage", data={"token": token})


def flagged_sdk_client(token: str):
    # ruleid: slack-api-calls-go-through-egress
    return WebClient(token=token)


def ok_through_transport(token: str):
    # ok: slack-api-calls-go-through-egress
    return slack_request(
        "POST",
        "https://slack.com/api/chat.postMessage",
        source="test",
        endpoint="chat.postMessage",
        headers={"Authorization": f"Bearer {token}"},
    )


def ok_egress_client(token: str):
    # ok: slack-api-calls-go-through-egress
    return SlackWebClient(token=token, source="test")


def ok_webhook():
    # ok: slack-api-calls-go-through-egress
    return requests.post("https://hooks.slack.com/services/example")
