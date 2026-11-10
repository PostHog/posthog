# Test cases for github-api-calls-go-through-egress rule.
# ruff: noqa: F841, E501
import httpx
import aiohttp
import requests
import urllib.request
from urllib.request import urlopen

from posthog.egress.github.transport import github_request


def flagged_literal_url(token: str):
    # ruleid: github-api-calls-go-through-egress
    return requests.get("https://api.github.com/user", headers={"Authorization": f"Bearer {token}"})


def flagged_fstring_url(repo: str):
    # ruleid: github-api-calls-go-through-egress
    return requests.post(f"https://api.github.com/repos/{repo}/issues", json={"title": "x"})


def flagged_generic_request(method: str):
    # ruleid: github-api-calls-go-through-egress
    return requests.request(method, "https://uploads.github.com/repos/o/r/releases/1/assets")


def ok_through_transport(token: str):
    # ok: github-api-calls-go-through-egress
    return github_request("GET", "https://api.github.com/user", source="integration", headers={})


def ok_other_host():
    # ok: github-api-calls-go-through-egress
    return requests.get("https://example.com/api")


GITHUB_API = "https://api.github.com"
GITHUB_USER_URL = "https://api.github.com/user"


def flagged_url_in_variable(token: str):
    url = "https://api.github.com/user"
    # ruleid: github-api-calls-go-through-egress-wide
    return requests.get(url, headers={"Authorization": f"Bearer {token}"})


def flagged_module_constant():
    # ruleid: github-api-calls-go-through-egress-wide
    return requests.get(GITHUB_USER_URL)


def flagged_concatenation(repo: str):
    # ruleid: github-api-calls-go-through-egress-wide
    return requests.get(GITHUB_API + "/repos/" + repo)


def flagged_fstring_with_constant(repo: str):
    # ruleid: github-api-calls-go-through-egress-wide
    return requests.get(f"{GITHUB_API}/repos/{repo}")


def flagged_session():
    # ruleid: github-api-calls-go-through-egress-wide
    return requests.Session().get("https://api.github.com/user")


def flagged_session_variable():
    session = requests.Session()
    # ruleid: github-api-calls-go-through-egress-wide
    return session.post(GITHUB_USER_URL)


def flagged_session_context_manager():
    with requests.Session() as session:
        # ruleid: github-api-calls-go-through-egress-wide
        return session.get(GITHUB_USER_URL)


def flagged_httpx_module_call():
    # ruleid: github-api-calls-go-through-egress-wide
    return httpx.get("https://api.github.com/user")


def flagged_httpx_client():
    # ruleid: github-api-calls-go-through-egress-wide
    return httpx.Client().get(GITHUB_USER_URL)


async def flagged_httpx_async_client():
    async with httpx.AsyncClient() as client:
        # ruleid: github-api-calls-go-through-egress-wide
        return await client.get(GITHUB_USER_URL)


async def flagged_aiohttp():
    async with aiohttp.ClientSession() as session:
        # ruleid: github-api-calls-go-through-egress-wide
        return await session.get(GITHUB_USER_URL)


def flagged_urlopen():
    # ruleid: github-api-calls-go-through-egress-wide
    return urllib.request.urlopen("https://uploads.github.com/repos/o/r/releases/1/assets")


def flagged_urlopen_request():
    # ruleid: github-api-calls-go-through-egress-wide
    return urlopen(urllib.request.Request(GITHUB_USER_URL))


def flagged_requests_options():
    # ruleid: github-api-calls-go-through-egress
    return requests.options("https://api.github.com/user")


def flagged_session_request_method_first():
    session = requests.Session()
    # ruleid: github-api-calls-go-through-egress-wide
    return session.request("POST", GITHUB_USER_URL)


async def flagged_aiohttp_request_method_first():
    async with aiohttp.ClientSession() as session:
        # ruleid: github-api-calls-go-through-egress-wide
        return await session.request("POST", GITHUB_USER_URL)


async def flagged_aiohttp_module_request():
    # ruleid: github-api-calls-go-through-egress-wide
    return aiohttp.request("GET", GITHUB_USER_URL)


async def flagged_aiohttp_assigned_session():
    session = aiohttp.ClientSession()
    # ruleid: github-api-calls-go-through-egress-wide
    return await session.get(GITHUB_USER_URL)


def ok_wide_url_helpers():
    # ok: github-api-calls-go-through-egress-wide
    httpx.URL(GITHUB_USER_URL)
    session = requests.Session()
    # ok: github-api-calls-go-through-egress-wide
    session.mount(GITHUB_USER_URL, adapter)

def ok_wide_other_host():
    url = "https://example.com/api"
    # ok: github-api-calls-go-through-egress-wide
    requests.get(url)
    # ok: github-api-calls-go-through-egress-wide
    httpx.get("https://example.com/api")
    # ok: github-api-calls-go-through-egress-wide
    return requests.Session().get("https://github.com/PostHog/posthog")


def ok_wide_through_transport(token: str):
    # ok: github-api-calls-go-through-egress-wide
    return github_request("GET", GITHUB_USER_URL, source="integration", headers={})
