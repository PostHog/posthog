import pytest

from posthog.helpers.url_redaction import redact_webhook_url


@pytest.mark.parametrize(
    "url,expected",
    [
        pytest.param("https://hooks.slack.com/services/T0/B0/tok", "https://hooks.slack.com/…", id="path"),
        pytest.param("https://hooks.example.com/svc/tok?k=v", "https://hooks.example.com/…", id="path_and_query"),
        pytest.param(
            "https://token:secret@hooks.example.com/path", "https://hooks.example.com/…", id="userinfo_credentials"
        ),
        pytest.param("https://hooks.example.com:8443/path?key=v", "https://hooks.example.com:8443/…", id="port"),
        pytest.param("https://[2001:db8::1]:9000/path", "https://[2001:db8::1]:9000/…", id="ipv6_host"),
    ],
)
def test_keeps_only_scheme_and_host(url: str, expected: str) -> None:
    assert redact_webhook_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("not-a-url", id="no_scheme_or_host"),
        pytest.param("", id="empty"),
        pytest.param("https://example.com:99999/path", id="port_out_of_range"),
        pytest.param("https://[2001:db8::1/path", id="unclosed_ipv6_bracket"),
    ],
)
def test_hides_urls_it_cannot_parse(url: str) -> None:
    assert redact_webhook_url(url) == "(hidden)"
