{% autoescape off %}# PostHog app

> This is the PostHog web app. Most pages need a login. Agents get better results from the MCP server or the API than from reading app pages.

- Do not crawl the app. Shared dashboards and shared links are private to the people who got them.
- After a person logs in, the app gives in-page tools through WebMCP. An agent in the browser can call them, so it does not need to click through the UI.

## Use PostHog from an agent

- Install and configure the PostHog SDK with the setup agent: `npx @posthog/wizard@latest`.
- Add PostHog MCP to your agent: `npx @posthog/wizard mcp add`.
- [MCP server](https://mcp.posthog.com/mcp): Connect an MCP client here to query data and manage flags, insights, experiments and more.
- [MCP server docs](https://posthog.com/docs/model-context-protocol): How to connect and authenticate.
- [Agent sign-up and authentication]({{ site_url }}/auth.md): Create an account or authenticate an existing user.
- [API reference](https://posthog.com/docs/api): REST API. It uses a personal API key.
- [Personal API keys]({{ site_url }}/settings/user-api-keys): Create a key here.

## Docs

- [PostHog docs](https://posthog.com/docs): Product and SDK docs.
- [Docs for LLMs](https://posthog.com/llms.txt): The full docs index in llms.txt format.
{% endautoescape %}
