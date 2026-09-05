# SDK Health release tracking

SDK Health groups recent events by `$lib` and `$lib_version` and compares each SDK with its stable GitHub releases.
The API and scheduled health checks share the registry in `products/growth/backend/constants.py`.
Release fetchers live in `products/growth/dags/github_sdk_versions.py`.

## Package-specific SDK identities

These SDKs appear separately in SDK Health, even when they share a repository or transport with another SDK.

| Event `$lib`         | Release repository                                          | Accepted release tags                                                    | Assessment rules |
| -------------------- | ----------------------------------------------------------- | ------------------------------------------------------------------------ | ---------------- |
| `posthog-kmp`        | [posthog-kmp](https://github.com/PostHog/posthog-kmp)       | Bare semver or `v` prefix                                                | Mobile           |
| `posthog-unity`      | [posthog-unity](https://github.com/PostHog/posthog-unity)   | Bare semver                                                              | Mobile           |
| `posthog-node-mcp`   | [posthog-js](https://github.com/PostHog/posthog-js)         | `@posthog/mcp@`                                                          | Server           |
| `posthog-python-mcp` | [posthog-python](https://github.com/PostHog/posthog-python) | Python package releases, as for `posthog-python`                         | Server           |
| `posthog-edge`       | [posthog-js](https://github.com/PostHog/posthog-js)         | `posthog-node@`, with historical Node release dates from posthog-js-lite | Server           |
| `posthog-convex`     | [posthog-js](https://github.com/PostHog/posthog-js)         | `@posthog/convex@`                                                       | Server           |
| `posthog-rails`      | [posthog-ruby](https://github.com/PostHog/posthog-ruby)     | `posthog-rails-v`                                                        | Server           |
| `posthog-aspnetcore` | [posthog-dotnet](https://github.com/PostHog/posthog-dotnet) | `PostHog.AspNetCore-v`                                                   | Server           |

Edge emits the Node SDK version, so it uses Node releases.
Node.js MCP, Convex, Rails, and ASP.NET Core emit their own package versions and must not use their transport SDK's releases.
Unity uses mobile assessment rules because users control when installed apps update, including on desktop platforms.

## Python MCP package versions

Python MCP ships inside the `posthog` package and uses the same release stream as `posthog-python`.
Its `$lib` remains `posthog-python-mcp`, while `$lib_version` must identify the installed Python package.

Older Python MCP clients emit a `0.x` integration version that does not identify the installed package.
SDK Health excludes those entries from assessment instead of comparing them with Python package releases and issuing false outdatedness warnings.
In mixed traffic, it assesses only the entries that use package versions.
Upgrade the Python SDK to a release that emits its package version to include that client's traffic in SDK Health.

## AI integrations

`$ai_lib` and `$ai_lib_version` are separate from the transport's `$lib` and `$lib_version`.
This registry assesses the transport SDK, not AI integration versions.
Adding an AI usage metric does not create a new SDK Health release stream.

## Adding another SDK

Verify the SDK's emitted identity and version in its source before choosing a release stream.
Register the identifier, release fetcher, assessment category, readable name, and frontend documentation links.
Extend the detection and release-dispatch tests, including sibling package tags when a repository contains multiple packages.
Regenerate OpenAPI types after changing the registry, since the SDK assessment serializer exposes it as an enum.
