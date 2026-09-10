# Desktop documentation

Start with the guide that matches the work you are doing. [AGENTS.md](../AGENTS.md) remains the source of truth when a guide conflicts with an architecture or code rule.

## Develop and test

| Guide | Use it for |
| --- | --- |
| [Local development](./LOCAL-DEVELOPMENT.md) | Connect the desktop app to a local PostHog instance. |
| [Architecture](./ARCHITECTURE.md) | Understand package layers, dependency injection, host boundaries, and feature placement. |
| [Code conventions](./CONVENTIONS.md) | Follow component, store, hook, styling, logging, and analytics conventions. |
| [Testing](./TESTING.md) | Choose and run unit, UI, end-to-end, interactive, and visual tests. |
| [Troubleshooting](./TROUBLESHOOTING.md) | Resolve common setup, native module, and signing failures. |

## Operate and release

| Guide | Use it for |
| --- | --- |
| [Updates](./UPDATES.md) | Understand versioning, release tags, and update publishing. |
| [Local auto-update testing](./AUTO-UPDATE-TESTING.md) | Exercise the packaged app's update flow without publishing a release. |
| [Announcements](./ANNOUNCEMENTS.md) | Configure and test remote in-app announcements. |
| [Cloud task artifacts](./CLOUD-TASK-ARTIFACTS.md) | Understand artifact notifications and dismissal behavior. |

## Feature references

| Guide | Use it for |
| --- | --- |
| [Deep links](./DEEP-LINKS.md) | Work with `posthog-code://` routes and OAuth callbacks. |
| [Pi extensions](./PI-EXTENSIONS.md) | Understand repository trust and desktop RPC behavior for Pi extensions. |
| [Cloud MCP import](./CLOUD-MCP-IMPORT.md) | Understand importing local MCP configuration into cloud task runs. |
| [Cloud MCP relay](./CLOUD-MCP-RELAY.md) | Understand the design for relaying local MCP servers to cloud task runs. |

## Design records

These documents capture design intent at a point in time. Check the current code and architecture rules before using them as implementation guidance.

- [Chat thread rebuild](./CHAT-REBUILD-SPEC.md)
- [Freeform React canvases](./CANVAS-FREEFORM-REACT-PLAN.md)
- [Browser tabs](./plans/browser-tabs.md)
- [Skills tab v2](./plans/skills-tab.md)
- [Quiet backstop narration](./superpowers/specs/2026-07-02-quiet-backstop-narration-design.md)

## App and package guides

- [Electron desktop app](../apps/code/README.md)
- [Mobile app](../apps/mobile/README.md)
- [Web app](../apps/web/README.md)
- [Agent framework](../packages/agent/README.md)
- [Harness](../packages/harness/README.md)
