# Pi extensions in PostHog Desktop

PostHog Desktop supports Pi extensions and packages in local Pi sessions through Pi's RPC mode. Cloud Pi sessions do not load local extensions.

For installation, discovery, authoring, and security guidance, see the [Pi documentation](https://pi.dev/docs/latest/) and [Pi extension documentation](https://pi.dev/docs/latest/extensions).

## Repository trust

Project-local Pi resources remain disabled until the repository is explicitly trusted. When PostHog Desktop detects project resources, it shows a trust control above the composer.

Trust decisions use Pi's native project trust store. A decision made for the registered main repository also applies to PostHog Desktop's managed worktrees for that repository. Trusting or revoking a repository restarts the local Pi runtime so Pi can rebuild its resource set while preserving the native task session.

Pi extensions execute inside the local Pi subprocess with the current user's permissions. Review a repository's Pi resources before trusting it.

## Desktop RPC behavior

PostHog Desktop supports extension tools, lifecycle hooks, slash commands, custom text messages, and the UI methods represented by Pi's RPC protocol. RPC dialogs, notifications, statuses, text widgets, titles, and editor text updates are rendered using Desktop UI.

Extension UI state is ephemeral. PostHog Desktop does not replay UI requests or maintain a separate snapshot across RPC reconnects or runtime replacement. Extensions that need to restore meaningful state should persist it in the Pi session and construct fresh UI from that state.

PostHog Desktop does not support terminal-only behavior such as arbitrary TUI components, rendering factories, raw terminal input handlers, custom headers or footers, themes, custom tool-call renderers, editor component replacement, editor autocomplete providers, or synchronous reads of the current composer text. Widgets are limited to text lines.

Extensions that support both environments should use Pi's RPC-compatible UI methods in Desktop and keep terminal-specific behavior behind Pi's TUI mode checks.
