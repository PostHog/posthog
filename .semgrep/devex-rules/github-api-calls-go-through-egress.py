# Test cases for github-api-calls-go-through-egress rule.
# ruff: noqa: F841, E501
import requests

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
