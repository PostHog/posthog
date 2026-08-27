/**
 * The overlay opened by pressing Enter on a focused footer item
 * (tui.md "Overlays" + "Pattern 1: Selection Dialog" framing).
 */

import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { DynamicBorder } from "@earendil-works/pi-coding-agent";
import { Container, Key, matchesKey, Text } from "@earendil-works/pi-tui";
import type { FooterItem } from "./inbox";

export async function showFooterItemOverlay(
  ctx: ExtensionContext,
  item: FooterItem,
): Promise<void> {
  await ctx.ui.custom<void>(
    (tui, theme, _keybindings, done) => {
      const border = (s: string) => theme.fg("accent", s);
      const container = new Container();

      container.addChild(new DynamicBorder(border));
      container.addChild(
        new Text(theme.fg("accent", theme.bold(item.label)), 1, 0),
      );
      container.addChild(new Text(theme.fg("text", item.detail), 1, 1));
      container.addChild(
        new Text(
          theme.fg("dim", new Date(item.createdAt).toLocaleString()),
          1,
          0,
        ),
      );
      container.addChild(new Text(theme.fg("dim", "enter/esc to close"), 1, 0));
      container.addChild(new DynamicBorder(border));

      return {
        render: (width: number) => container.render(width),
        invalidate: () => container.invalidate(),
        handleInput: (data: string) => {
          if (matchesKey(data, Key.enter) || matchesKey(data, Key.escape)) {
            done();
            return;
          }
          tui.requestRender();
        },
      };
    },
    {
      overlay: true,
      overlayOptions: {
        anchor: "bottom-center",
        width: "60%",
        minWidth: 40,
        margin: 1,
      },
    },
  );
}
