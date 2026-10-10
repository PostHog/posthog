# Using @posthog/sdk

Read [README.md](README.md) when configuring authentication, project selection, or a Tasks proxy.
Run `posthog-sdk search "<task>"`, then `posthog-sdk describe <method>` to discover the method and its input/output interfaces without credentials.
`catalog.json` is the offline index; its entries point to full descriptions and source/declaration files in this package.
Import `{ client }` from `@posthog/sdk` to use environment defaults, or `createPostHogClient` for explicit configuration.
Inspect the method's required scopes and result type before calling it. `coverage.json` maps every registered MCP tool to its SDK method.
