## 2.0.0 - 2025-09-30

### Major Release

`posthog-elixir` was fully reworked. Check [migration guide](MIGRATION.md#v1-v2)
for some tips on how to upgrade.

Huge thanks to community member [@martosaur](https://github.com/martosaur) for contributing this new version.

### What's new

- Elixir v1.17+ required
- Event capture is now offloaded to background workers with automatic batching
- [Context](README.md#context) mechanism for easier property propagation
- [Error Tracking](README.md#error-tracking) support
- New `PostHog.FeatureFlags` module for working with feature flags
- [Test mode](`PostHog.Test`) for easier testing
- Customizable [HTTP client](`PostHog.API.Client`) with Req as the default
- [Plug integration](`PostHog.Integrations.Plug`) for automatically capturing common HTTP properties

## 1.1.0 - 2025-07-01

- Expose `capture/2` `b077aba849126c63f1c7a82b6ad9d21945871a4a`

## 1.0.3 - 2025-06-02

- Fix implementation for structs `2cdc6f578a192fd751ce105018a7f78b7ed8f852`

## 1.0.2 - 2025-04-17

- More small changes to docs `147795c21a58e2308fbd43b571d9ba978c8a8a3b`

## 1.0.1 - 2025-04-17

- Small changes to docs `f3578a7006fb8d6cb19f36e19b1387243a12bd21`

## 1.0.0 - 2025-04-17

### Big Release

`posthog-elixir` is now officially stable and running on v1. There are some breaking changes and some general improvements. Check [MIGRATION.md](./MIGRATION.md#v0-v1) for a guide on how to migrate.

### What's changed

- Elixir v1.14+ is now a requirement
- Feature Flags now return a key called `payload` rather than `value` to better align with the other SDKs
- PostHog now requires you to initialize `Posthog.Application` alongside your supervisor tree. This is required because of our `Cachex` system to properly track your FF usage.
  - We'll also include local evaluation in the near term, which will also require a GenServer, therefore, requiring us to use a Supervisor.
- Added `enabled_capture` configuration option to disable PostHog tracking in development/test environments
- `PostHog.capture` now requires `distinct_id` as a required second argument

## 0.4.4 - 2025-04-14

Fix inconsistent docs for properties - [#13]

## 0.4.3 - 2025-04-14

Improve docs setup - [#12]

## 0.4.2 - 2025-03-27

Allow `atom()` property keys - [#11]

## 0.4.1 - 2025-03-12

Fix feature flags broken implementation - [#10]

## 0.4.0 - 2025-02-11

Documentation + OTP/Elixir version bumps

## 0.3.0 - 2025-01-09

- Initial feature flags implementation (#7)

## 0.2.0 - 2024-05-04

- Allow extra headers (#3)

## 0.1.0 - 2020-06-06

- Initial release
