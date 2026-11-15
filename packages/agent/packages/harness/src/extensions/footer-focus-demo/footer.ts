/**
 * The custom footer itself (tui.md "Pattern 6: Custom Footer" +
 * "Pattern 4: Persistent Status Indicator", combined into one component).
 *
 * Renders the inbox's items, highlighting whichever one currently has
 * keyboard focus, plus a one-line hint that changes depending on whether
 * the footer or the editor currently owns the arrow keys.
 */

import type { Theme } from "@earendil-works/pi-coding-agent";
import { truncateToWidth } from "@earendil-works/pi-tui";
import type { FooterInbox } from "./inbox";

export function renderFooterLines(
  inbox: FooterInbox,
  theme: Theme,
  width: number,
): string[] {
  if (!inbox.hasItems()) {
    return [
      truncateToWidth(theme.fg("dim", "footer-focus-demo: no items"), width),
    ];
  }

  const focusedIndex = inbox.getFocusedIndex();
  const itemLines = inbox.getItems().map((item, i) => {
    const focused = i === focusedIndex;
    const marker = focused ? "▶ " : "  ";
    const label = truncateToWidth(`${marker}${item.label}`, width);
    return focused
      ? theme.bg("selectedBg", theme.fg("accent", label))
      : theme.fg("muted", label);
  });

  const hint = inbox.isFocused()
    ? theme.fg("dim", "↑/↓ move · enter open · esc back to editor")
    : theme.fg("dim", "↓ from an empty editor to focus notifications");

  return [...itemLines, truncateToWidth(hint, width)];
}
