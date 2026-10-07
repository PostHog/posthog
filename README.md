<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/posthog-logo-dark.svg">
    <img alt="PostHog logo" src=".github/posthog-logo-light.svg" width="440">
  </picture>
</p>
<p align="center">
  <a href='https://github.com/PostHog/posthog/graphs/contributors'><img alt="GitHub contributors" src="https://img.shields.io/github/contributors/posthog/posthog"/></a>
  <a href='http://makeapullrequest.com'><img alt='PRs Welcome' src='https://img.shields.io/badge/PRs-welcome-brightgreen.svg?style=shields'/></a>
  <img alt="Docker Pulls" src="https://img.shields.io/docker/pulls/posthog/posthog"/>
  <a href="https://github.com/PostHog/posthog/commits/master"><img alt="GitHub commit activity" src="https://img.shields.io/github/commit-activity/m/posthog/posthog"/> </a>
  <a href="https://github.com/PostHog/posthog/issues?q=is%3Aissue%20state%3Aclosed"><img alt="GitHub closed issues" src="https://img.shields.io/github/issues-closed/posthog/posthog"/> </a>
</p>

<p align="center">
  <a href="https://posthog.com/docs">Docs</a> - <a href="https://posthog.com/community">Community</a> - <a href="https://posthog.com/roadmap">Roadmap</a> - <a href="https://posthog.com/why">Why PostHog?</a> - <a href="https://posthog.com/changelog">Changelog</a> - <a href="https://github.com/PostHog/posthog/issues/new?assignees=&labels=bug&template=bug_report.yml">Bug reports</a>
</p>

<p align="center">
  <a href="https://www.youtube.com/watch?v=1FZji2L-LmM">
    <img src="https://res.cloudinary.com/dmukukwp6/image/upload/demo_thumb_68d0d8d56d" alt="PostHog Demonstration">
  </a>
</p>

## PostHog is your product's context layer

[PostHog](https://posthog.com/) ingests and stores your analytics, errors, replays, and business data so you and your agents can query and act on it. It gives you every tool you need to build a successful product, and captures the context agents need to diagnose problems, uncover opportunities, and ship fixes:

- [Product analytics](https://posthog.com/product-analytics): Autocapture or manually instrument event-based analytics to understand user behavior. Analyze your data with visualizations or SQL.
- [Web analytics](https://posthog.com/web-analytics): Monitor web traffic and user sessions with a GA-like dashboard. Track conversion, web vitals, and revenue.
- [AI observability](https://posthog.com/ai-observability): Capture traces, generations, latency, and cost for your LLM-powered app. Run LLM-as-a-judge evaluations to catch regressions.
- [MCP analytics](https://posthog.com/docs/mcp-analytics) (beta): See how agents actually use your MCP server.
- [Session replay](https://posthog.com/session-replay): Watch real user sessions from your website or mobile app to diagnose issues and understand user behavior.
- [Replay Vision](https://posthog.com/replay-vision): Let AI watch your recordings for you and turn them into queryable observations.
- [Heatmaps](https://posthog.com/heatmaps): See where users click, scroll, and move on your site.
- [Feature flags](https://posthog.com/feature-flags): Safely roll out features to select users or cohorts.
- [Experiments](https://posthog.com/experiments): Test changes and measure their statistical impact on goal metrics. Set up experiments with no code, too.
- [Early access features](https://posthog.com/early-access-features) (beta): Let users opt into betas and register interest in upcoming features.
- [Error tracking](https://posthog.com/error-tracking): Track errors, get alerts, and resolve issues to improve your product.
- [Logs](https://posthog.com/logs): Ingest, search, and analyze log data alongside the rest of your product data.
- [Tracing](https://posthog.com/tracing): Follow distributed traces straight to the line of code that broke.
- [Surveys](https://posthog.com/surveys): Ask anything with our collection of no-code survey templates, or build custom surveys with our survey builder.
- [Support](https://posthog.com/support): Run customer support with a chat widget and a unified inbox, next to the product data behind each ticket.
- [Group analytics](https://posthog.com/group-analytics): Analyze multi-seat accounts and other groups of users.
- [Workflows](https://posthog.com/workflows): Automate actions and messages to your users, triggered by your product data.
- [Context warehouse](https://posthog.com/context-warehouse): Collect, store, transform, and query all the context behind your product. Includes a managed warehouse, 120+ sources, and a SQL editor with BI and data visualization.
- [CDP](https://posthog.com/cdp): Run custom filters and transformations on your incoming data. Send it to 25+ tools or any webhook in real time, or batch export large amounts to your warehouse.
- [Endpoints](https://posthog.com/endpoints) (beta): Build custom API endpoints powered by your PostHog data.
- [PostHog AI](https://posthog.com/ai): Ask your product data anything. PostHog AI builds insights, writes SQL, and finds replays for you.
- [Self-driving](https://posthog.com/self-driving): Turn signals in your product data (errors, rage clicks, failed queries, and more) into researched reports and pull requests, delivered to your Inbox for you to review and merge.

You can steer it all from [Slack](https://posthog.com/slack), [web](https://posthog.com/ai), desktop ([PostHog Desktop](https://posthog.com/desktop)), or your own editor via [the MCP](https://posthog.com/mcp). If you are an agent, the docs are indexed for you at [posthog.com/llms.txt](https://posthog.com/llms.txt) and the changelog is plain Markdown at [posthog.com/changelog.md](https://posthog.com/changelog.md).

Best of all, all of this is free to use with a [generous monthly free tier](https://posthog.com/pricing) for each tool. Get started by signing up for [PostHog Cloud US](https://us.posthog.com/signup) or [PostHog Cloud EU](https://eu.posthog.com/signup).

## Table of Contents

- [PostHog is your product's context layer](#posthog-is-your-products-context-layer)
- [Table of Contents](#table-of-contents)
- [Getting started with PostHog](#getting-started-with-posthog)
  - [PostHog Cloud (Recommended)](#posthog-cloud-recommended)
  - [Self-hosting the open-source hobby deploy (Advanced)](#self-hosting-the-open-source-hobby-deploy-advanced)
- [Setting up PostHog](#setting-up-posthog)
- [Learning more about PostHog](#learning-more-about-posthog)
- [Contributing](#contributing)
- [Open-source vs. paid](#open-source-vs-paid)
- [We’re hiring!](#were-hiring)

## Getting started with PostHog

### PostHog Cloud (Recommended)

The fastest and most reliable way to get started with PostHog is signing up for free to [PostHog Cloud](https://us.posthog.com/signup) or [PostHog Cloud EU](https://eu.posthog.com/signup). Your first 1 million events, 5k recordings, 1M flag requests, 100k exceptions, 10GB of logs, and 1500 survey responses are free every month, after which you pay based on usage.

### Self-hosting the open-source hobby deploy (Advanced)

If you want to self-host PostHog, you can deploy a hobby instance in one line on Linux with Docker (recommended 4GB memory):

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/posthog/posthog/HEAD/bin/deploy-hobby)"
```

Open source deployments should scale to approximately 100k events per month, after which we recommend [migrating to a PostHog Cloud](https://posthog.com/docs/migrate/migrate-to-cloud).

We _do not_ provide customer support or offer guarantees for open source deployments. See our [self-hosting docs](https://posthog.com/docs/self-host), [troubleshooting guide](https://posthog.com/docs/self-host/deploy/troubleshooting), and [disclaimer](https://posthog.com/docs/self-host/open-source/disclaimer) for more info.

## Setting up PostHog

Once you've got a PostHog instance, you can set it up by installing our [JavaScript web snippet](https://posthog.com/docs/getting-started/install?tab=snippet), one of [our SDKs](https://posthog.com/docs/getting-started/install?tab=sdks), or by [using our API](https://posthog.com/docs/getting-started/install?tab=api). You can also connect [the MCP](https://posthog.com/mcp) to bring PostHog into Claude Code, Cursor, or any MCP-compatible agent.

We have SDKs and libraries for popular languages and frameworks like:

| Frontend                                              | Mobile                                                          | Backend                                             |
| ----------------------------------------------------- | --------------------------------------------------------------- | --------------------------------------------------- |
| [JavaScript](https://posthog.com/docs/libraries/js)   | [React Native](https://posthog.com/docs/libraries/react-native) | [Python](https://posthog.com/docs/libraries/python) |
| [Next.js](https://posthog.com/docs/libraries/next-js) | [Android](https://posthog.com/docs/libraries/android)           | [Node](https://posthog.com/docs/libraries/node)     |
| [React](https://posthog.com/docs/libraries/react)     | [iOS](https://posthog.com/docs/libraries/ios)                   | [PHP](https://posthog.com/docs/libraries/php)       |
| [Vue](https://posthog.com/docs/libraries/vue-js)      | [Flutter](https://posthog.com/docs/libraries/flutter)           | [Ruby](https://posthog.com/docs/libraries/ruby)     |

Beyond this, we have docs and guides for [Go](https://posthog.com/docs/libraries/go), [.NET/C#](https://posthog.com/docs/libraries/dotnet), [Django](https://posthog.com/docs/libraries/django), [Angular](https://posthog.com/docs/libraries/angular), [WordPress](https://posthog.com/docs/libraries/wordpress), [Webflow](https://posthog.com/docs/libraries/webflow), and more.

Once you've installed PostHog, see our [product docs](https://posthog.com/docs/product-os) for more information on how to set up [product analytics](https://posthog.com/docs/product-analytics/capture-events), [web analytics](https://posthog.com/docs/web-analytics/getting-started), [session replays](https://posthog.com/docs/session-replay/how-to-watch-recordings), [feature flags](https://posthog.com/docs/feature-flags/creating-feature-flags), [experiments](https://posthog.com/docs/experiments/creating-an-experiment), [error tracking](https://posthog.com/docs/error-tracking/installation#setting-up-exception-autocapture), [surveys](https://posthog.com/docs/surveys/installation), [data sources](https://posthog.com/docs/cdp/sources), and more.

## Learning more about PostHog

Our code isn't the only thing that's open source 😳. We also open source our [company handbook](https://posthog.com/handbook) which details our [strategy](https://posthog.com/handbook/why-does-posthog-exist), [ways of working](https://posthog.com/handbook/company/culture), and [processes](https://posthog.com/handbook/team-structure).

Curious about how to make the most of PostHog? We wrote a guide to [winning with PostHog](https://posthog.com/docs/new-to-posthog/getting-hogpilled) which walks you through the basics of [measuring activation](https://posthog.com/docs/new-to-posthog/activation), [tracking retention](https://posthog.com/docs/new-to-posthog/retention), and [capturing revenue](https://posthog.com/docs/new-to-posthog/revenue).

## Contributing

We <3 contributions big and small:

- Vote on features or get early access to beta functionality in our [roadmap](https://posthog.com/roadmap)
- Open a PR (see our instructions on [developing PostHog locally](https://posthog.com/handbook/engineering/developing-locally))
- Submit a feature request on [our roadmap](https://posthog.com/roadmap) or a [bug report](https://github.com/PostHog/posthog/issues/new?assignees=&labels=bug&template=bug_report.yml)

For an overview of the codebase structure, see [monorepo layout](docs/internal/monorepo-layout.md) and [products](products/README.md).

## Open-source vs. paid

This repo is available under the [MIT expat license](https://github.com/PostHog/posthog/blob/master/LICENSE), except for the `ee` directory (which has its [license here](https://github.com/PostHog/posthog/blob/master/ee/LICENSE)) if applicable.

Need _absolutely 💯% FOSS_? Check out our [posthog-foss](https://github.com/PostHog/posthog-foss) repository, which is purged of all proprietary code and features.

The pricing for our paid plan is completely transparent and available on [our pricing page](https://posthog.com/pricing).

## We're hiring!

<img src="https://raw.githubusercontent.com/PostHog/brand/main/assets/hoggies/png/coding-group.png" alt="A group of hedgehogs writing code together" width="350px"/>

Hey! If you're reading this, you've proven yourself as a dedicated README reader.

You might also make a great addition to our team. We're growing fast [and would love for you to join us](https://posthog.com/careers).
