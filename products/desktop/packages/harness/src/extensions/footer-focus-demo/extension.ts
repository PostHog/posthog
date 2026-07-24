/**
 * footer-focus-demo — POC extension demonstrating:
 *
 *   - a custom footer (tui.md "Pattern 6") that lists items and highlights
 *     whichever one has keyboard focus (tui.md "Pattern 4" for the
 *     underlying status-indicator idea)
 *   - moving that focus into/out of the footer with Down/Up/Escape, via a
 *     custom editor (tui.md "Pattern 7")
 *   - opening an overlay (tui.md "Overlays") with Enter when an item is
 *     focused
 *
 * Seeded with two demo items on session start so the flow is reachable
 * immediately: clear the editor, press Down to focus the footer, Up/Down
 * to move between items, Enter to open the overlay, Esc/Up-from-top to
 * return focus to the editor.
 *
 * `/footer-demo:add [text]` and `/footer-demo:clear` let you add/remove
 * items at runtime to see the "IF an item is present" behavior for
 * yourself (the footer/editor hand-off simply does nothing when the list
 * is empty).
 */

import type {
  ExtensionAPI,
  ExtensionFactory,
} from "@earendil-works/pi-coding-agent";
import { FooterAwareEditor } from "./editor";
import { renderFooterLines } from "./footer";
import { FooterInbox } from "./inbox";
import { showFooterItemOverlay } from "./overlay";

export function createFooterFocusDemoExtension(): ExtensionFactory {
  return (pi: ExtensionAPI) => {
    const inbox = new FooterInbox();

    pi.on("session_start", (_event, ctx) => {
      if (!inbox.hasItems()) {
        inbox.add({
          id: "welcome",
          label: "Welcome notification",
          detail:
            "Clear the editor and press Down to focus this footer, then Enter to open it.",
          createdAt: Date.now(),
        });
        inbox.add({
          id: "second",
          label: "Second item",
          detail:
            "Up/Down move between footer items while focused. Esc, or Up from the top item, returns focus to the editor.",
          createdAt: Date.now(),
        });
      }

      ctx.ui.setFooter((tui, _theme, _footerData) => {
        const unsubscribe = inbox.setOnChange(() => tui.requestRender());
        return {
          dispose: unsubscribe,
          invalidate() {},
          render(width: number): string[] {
            return renderFooterLines(inbox, ctx.ui.theme, width);
          },
        };
      });

      ctx.ui.setEditorComponent(
        (tui, theme, keybindings) =>
          new FooterAwareEditor(tui, theme, keybindings, inbox, () => {
            const item = inbox.getFocusedItem();
            if (item) void showFooterItemOverlay(ctx, item);
          }),
      );
    });

    pi.on("session_shutdown", () => {
      inbox.clear();
    });

    pi.registerCommand("footer-demo:add", {
      description: "Add a demo item to the focusable footer",
      handler: async (args, ctx) => {
        const label = args.trim() || `Item ${inbox.getItems().length + 1}`;
        inbox.add({
          id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          label,
          detail:
            args.trim() || "Demo notification body — no detail was provided.",
          createdAt: Date.now(),
        });
        ctx.ui.notify(`Added footer item: ${label}`, "info");
      },
    });

    pi.registerCommand("footer-demo:clear", {
      description: "Clear all focusable footer items",
      handler: async (_args, ctx) => {
        inbox.clear();
        ctx.ui.notify("Cleared footer items", "info");
      },
    });
  };
}

export default function footerFocusDemo(
  pi: ExtensionAPI,
): void | Promise<void> {
  return createFooterFocusDemoExtension()(pi);
}
