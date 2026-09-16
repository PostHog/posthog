# Dashboard keyboard shortcuts

Press `E` to enter layout editing on a dashboard with at least one tile and edit access.
This also works while you edit dashboard filters.
The shortcut does not activate while you type in an input, text area, or content editor.

During layout editing, press `E` or `Command+Option+S` (`Ctrl+Alt+S` on Windows and Linux) to save the layout.
Press `Escape` to cancel layout editing.

`DashboardCustomizeButton` attaches `Shortcut` directly to `LemonButton`.
The shortcut needs a reference to the DOM button to register and trigger a click.
If a component wraps the button, it must forward that reference or contain the shortcut itself.

`DashboardHeader.test.tsx` covers the `E` key from view mode and filter editing, and checks that users with view access cannot start layout editing.
