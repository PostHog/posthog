# Pi extensions in PostHog Code

PostHog Code desktop supports Pi's existing extension and package model for local Pi sessions. This is a bridge to Pi's RPC extension protocol, not a general PostHog Code plugin API: extensions run inside the local Pi subprocess and do not load arbitrary React or Electron main-process code.

Cloud Pi sessions do not load local extensions.

## Install and discovery

The bundled Pi CLI is branded as `hog`. Install a package globally with:

```bash
hog install npm:@scope/package
hog install git:github.com/owner/repository@v1
hog install https://github.com/owner/repository
```

Global installs are recorded in `~/.pi/agent/settings.json`. npm packages are installed under `~/.pi/agent/npm/`, and git packages under `~/.pi/agent/git/`. Standalone global extensions can also be placed at:

- `~/.pi/agent/extensions/*.ts`
- `~/.pi/agent/extensions/*/index.ts`

Restart or resume a local Pi session after changing installed resources. Package-provided extensions, skills, prompt templates, and other Pi resources use Pi's normal global discovery rules.

Project-local resources can be placed in Pi's normal repository locations, including `.pi/extensions/`, `.pi/settings.json`, `.pi/skills/`, and `.pi/prompts/`. They remain disabled until the repository is explicitly trusted in the local Pi session. When project resources are detected, PostHog Code shows a trust control above the composer.

Trust decisions are persisted with Pi's native project trust store at `~/.pi/agent/trust.json`. Trust is associated with the registered main repository, so the same decision applies to PostHog Code's managed worktrees for that repository. Trusting or revoking trust restarts the local Pi runtime so its resource set is rebuilt while preserving the task's native session. Revoking trust disables project-local resources on that restart.

## Security warning

**Pi extensions and packages run with full system permissions as your user.** They can execute arbitrary code, access files outside the current repository, start processes, read available credentials, and use the network. Skills can also instruct the model to perform arbitrary actions. Review the complete source and dependency tree before trusting a repository or installing third-party packages, and pin versions or git revisions where possible.

Repository trust is opt-in and local-only. Do not trust a repository merely to dismiss the warning; inspect its `.pi` resources and dependencies first.

## Supported behavior

The desktop RPC bridge preserves Pi's native extension behavior, including:

- extension tools and lifecycle hooks
- slash commands
- global and trusted project resources and extension state
- custom text messages
- selection, confirmation, single-line input, and multiline editor dialogs
- notifications, compact session statuses, text widgets above or below the composer, task-view document titles, and composer replacement/prefill

Dialog requests are shown one at a time per task. They can be cancelled, and timed requests are removed when their Pi timeout expires. Extension failures are non-fatal notifications and do not fail the agent run.

## RPC versus TUI

PostHog Code runs Pi in RPC mode, not in Pi's terminal UI. Only behavior represented by Pi's RPC protocol can cross the boundary. In particular, PostHog Code does not support arbitrary Pi TUI components or rendering factories, raw terminal input handlers, custom headers/footers/themes, custom tool-call renderers, editor component replacement, editor autocomplete providers, or synchronous reads of the current composer text. Widgets are text lines only.

An extension that depends on those TUI-only APIs may still load, but those visual or terminal-specific portions are ignored by Pi RPC mode. Use the supported RPC dialog and fire-and-forget UI methods for an extension intended to work in PostHog Code.
