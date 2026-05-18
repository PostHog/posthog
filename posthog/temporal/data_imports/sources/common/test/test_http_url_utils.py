import pytest

from posthog.temporal.data_imports.sources.common.http.url_utils import host_of, scrub_url, url_template


@pytest.mark.parametrize(
    "url,expected",
    [
        # No query string — no change
        ("https://api.example.com/v1/users", "https://api.example.com/v1/users"),
        # Single redact-listed param
        (
            "https://api.example.com/v1/users?api_key=secret",
            "https://api.example.com/v1/users?api_key=REDACTED",
        ),
        # Mixed params: only the secret is redacted
        (
            "https://api.example.com/v1/users?api_key=secret&page=2",
            "https://api.example.com/v1/users?api_key=REDACTED&page=2",
        ),
        # Case-insensitive matching of param name
        (
            "https://api.example.com/?API_KEY=secret",
            "https://api.example.com/?API_KEY=REDACTED",
        ),
        # All known auth-bearing names
        (
            "https://x.test/?apikey=a&access_token=b&auth=c&auth_token=d&client_secret=e",
            "https://x.test/?apikey=REDACTED&access_token=REDACTED&auth=REDACTED&auth_token=REDACTED&client_secret=REDACTED",
        ),
        (
            "https://x.test/?key=a&password=b&secret=c&sig=d&signature=e&token=f",
            "https://x.test/?key=REDACTED&password=REDACTED&secret=REDACTED&sig=REDACTED&signature=REDACTED&token=REDACTED",
        ),
        # Unrelated params are preserved verbatim
        (
            "https://api.example.com/?cursor=abc123&limit=50",
            "https://api.example.com/?cursor=abc123&limit=50",
        ),
        # Fragment + path are preserved
        (
            "https://api.example.com/v1/users?token=abc#frag",
            "https://api.example.com/v1/users?token=REDACTED#frag",
        ),
    ],
)
def test_scrub_url_redacts_auth_params(url: str, expected: str) -> None:
    assert scrub_url(url) == expected


def test_scrub_url_preserves_param_order():
    """Order of params in the output must match the input."""
    raw = "https://x.test/?a=1&token=secret&b=2&api_key=secret2&c=3"
    out = scrub_url(raw)
    # Just verify positions of names, not values
    assert out.index("a=") < out.index("token=") < out.index("b=") < out.index("api_key=") < out.index("c=")


def test_scrub_url_handles_repeated_keys():
    """When a key appears twice, both values are redacted."""
    out = scrub_url("https://x.test/?token=a&token=b")
    assert out == "https://x.test/?token=REDACTED&token=REDACTED"


def test_scrub_url_returns_input_on_garbage():
    """Anything urlsplit can parse goes through; truly broken inputs come back unchanged."""
    # urlsplit is tolerant — most "weird" inputs still parse
    assert scrub_url("") == ""
    assert scrub_url("not-a-url") == "not-a-url"


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://api.example.com/v1/users/12345", "https://api.example.com/v1/users/{id}"),
        (
            "https://api.example.com/v1/users/abcdef0123456789abcdef0123456789",
            "https://api.example.com/v1/users/{id}",
        ),
        (
            "https://api.example.com/v1/orgs/22222222-2222-2222-2222-222222222222/projects",
            "https://api.example.com/v1/orgs/{id}/projects",
        ),
        # Non-id segments preserved
        ("https://api.example.com/v1/users/me", "https://api.example.com/v1/users/me"),
        # Query string dropped
        (
            "https://api.example.com/v1/users?cursor=abc",
            "https://api.example.com/v1/users",
        ),
        # Empty path
        ("https://api.example.com/", "https://api.example.com/"),
    ],
)
def test_url_template_replaces_id_segments(url: str, expected: str) -> None:
    assert url_template(url) == expected


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://api.example.com/v1/users", "api.example.com"),
        ("http://localhost:8000/path", "localhost:8000"),
        ("https://api.example.com:443/", "api.example.com:443"),
        ("not-a-url", "unknown"),
        ("", "unknown"),
    ],
)
def test_host_of(url: str, expected: str) -> None:
    assert host_of(url) == expected
