# ruff: noqa: F841
import aiohttp
import httpx
import requests
import slack_sdk
import urllib.request
from slack_sdk import AsyncWebClient
from slack_sdk import WebClient
from slack_sdk import WebClient as AliasedWebClient

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


SLACK_POST_MESSAGE = "https://slack.com/api/chat.postMessage"


def flagged_aliased_sdk_client(token: str):
    # ruleid: slack-api-calls-go-through-egress-wide
    return AliasedWebClient(token=token)


def flagged_async_sdk_client(token: str):
    # ruleid: slack-api-calls-go-through-egress-wide
    return AsyncWebClient(token=token)


def flagged_module_sdk_client(token: str):
    # ruleid: slack-api-calls-go-through-egress-wide
    return slack_sdk.WebClient(token=token)


def flagged_variable_url(token: str):
    # ruleid: slack-api-calls-go-through-egress-wide
    return requests.post(SLACK_POST_MESSAGE, data={"token": token})


def flagged_session():
    # ruleid: slack-api-calls-go-through-egress-wide
    return requests.Session().post("https://slack.com/api/chat.postMessage")


def flagged_httpx():
    # ruleid: slack-api-calls-go-through-egress-wide
    return httpx.post(SLACK_POST_MESSAGE)


async def flagged_httpx_async_client():
    async with httpx.AsyncClient() as client:
        # ruleid: slack-api-calls-go-through-egress-wide
        return await client.post(SLACK_POST_MESSAGE)


async def flagged_aiohttp():
    async with aiohttp.ClientSession() as session:
        # ruleid: slack-api-calls-go-through-egress-wide
        return await session.post(SLACK_POST_MESSAGE)


def flagged_urlopen():
    # ruleid: slack-api-calls-go-through-egress-wide
    return urllib.request.urlopen(SLACK_POST_MESSAGE)


def flagged_requests_options():
    # ruleid: slack-api-calls-go-through-egress-wide
    return requests.options(SLACK_POST_MESSAGE)


def flagged_session_request_method_first():
    session = requests.Session()
    # ruleid: slack-api-calls-go-through-egress-wide
    return session.request("POST", SLACK_POST_MESSAGE)


async def flagged_aiohttp_request_method_first():
    async with aiohttp.ClientSession() as session:
        # ruleid: slack-api-calls-go-through-egress-wide
        return await session.request("POST", SLACK_POST_MESSAGE)


async def flagged_aiohttp_module_request():
    # ruleid: slack-api-calls-go-through-egress-wide
    return aiohttp.request("GET", SLACK_POST_MESSAGE)


async def flagged_aiohttp_assigned_session():
    session = aiohttp.ClientSession()
    # ruleid: slack-api-calls-go-through-egress-wide
    return await session.get(SLACK_POST_MESSAGE)


def ok_wide_url_helpers():
    # ok: slack-api-calls-go-through-egress-wide
    httpx.URL(SLACK_POST_MESSAGE)
    session = requests.Session()
    # ok: slack-api-calls-go-through-egress-wide
    session.mount(SLACK_POST_MESSAGE, adapter)

def ok_wide_webhook():
    # ok: slack-api-calls-go-through-egress-wide
    httpx.post("https://hooks.slack.com/services/example")
    # ok: slack-api-calls-go-through-egress-wide
    return requests.Session().post("https://hooks.slack.com/services/example")


def ok_wide_egress_client(token: str):
    # ok: slack-api-calls-go-through-egress-wide
    return SlackWebClient(token=token, source="test")


def flagged_urlopen_request():
    # ruleid: slack-api-calls-go-through-egress-wide
    return urllib.request.urlopen(urllib.request.Request(SLACK_POST_MESSAGE))
