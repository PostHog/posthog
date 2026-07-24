/** Overlay showing every active subagent run, keyboard-navigable, with live task output and usage. */

import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { getMarkdownTheme } from "@earendil-works/pi-coding-agent";
import {
  Container,
  Key,
  Markdown,
  matchesKey,
  Spacer,
  Text,
  truncateToWidth,
  visibleWidth,
} from "@earendil-works/pi-tui";
import { getFinalOutput } from "./format";
import { formatUsageStats, styleMultiline } from "./render";
import { listAgentRuns, subscribeToAgentRuns } from "./status-registry";

function formatElapsed(startedAt: number): string {
  const seconds = Math.round((Date.now() - startedAt) / 1000);
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

function drawBox(
  lines: string[],
  width: number,
  border: (s: string) => string,
): string[] {
  const innerWidth = Math.max(1, width - 4);
  const top = border(`\u256d${"\u2500".repeat(Math.max(0, width - 2))}\u256e`);
  const bottom = border(
    `\u2570${"\u2500".repeat(Math.max(0, width - 2))}\u256f`,
  );
  const side = border("\u2502");
  const boxed = lines.map((line) => {
    const clipped = truncateToWidth(line, innerWidth);
    const pad = " ".repeat(Math.max(0, innerWidth - visibleWidth(clipped)));
    return truncateToWidth(`${side} ${clipped}${pad} ${side}`, width);
  });
  return [top, ...boxed, bottom];
}

export async function showSubagentStatusOverlay(
  ctx: ExtensionContext,
): Promise<void> {
  await ctx.ui.custom<void>(
    (tui, theme, _keybindings, done) => {
      let selectedIndex = 0;
      const border = (s: string) => theme.fg("accent", s);

      const unsubscribe = subscribeToAgentRuns(() => {
        if (listAgentRuns().length === 0) {
          done();
          return;
        }
        tui.requestRender();
      });
      // Registry updates occur at model-turn boundaries. Tick separately so
      // elapsed time stays live while a child is thinking between updates.
      const elapsedTimer = setInterval(() => tui.requestRender(), 1000);

      return {
        invalidate() {},
        dispose: () => {
          clearInterval(elapsedTimer);
          unsubscribe();
        },
        render(width: number): string[] {
          const runs = listAgentRuns();
          if (runs.length === 0) return [];
          selectedIndex = Math.min(selectedIndex, runs.length - 1);

          const container = new Container();
          container.addChild(
            new Text(
              theme.fg(
                "accent",
                theme.bold(`Subagents (${runs.length} running)`),
              ),
              0,
              0,
            ),
          );

          for (const [i, run] of runs.entries()) {
            const marker = i === selectedIndex ? "\u25b6 " : "  ";
            const label = `${marker}${run.agent} \u00b7 ${formatElapsed(run.startedAt)}`;
            const line =
              i === selectedIndex
                ? theme.bg("selectedBg", theme.fg("accent", label))
                : theme.fg("muted", label);
            container.addChild(new Text(line, 0, 0));
          }

          const selected = runs[selectedIndex];
          if (selected) {
            container.addChild(
              new Text(
                theme.fg("muted", "\u2500".repeat(Math.max(0, width - 4))),
                0,
                0,
              ),
            );
            const usageStr = formatUsageStats(selected.usage, selected.model);
            if (usageStr)
              container.addChild(new Text(theme.fg("dim", usageStr), 0, 0));
            container.addChild(new Spacer(1));
            container.addChild(
              new Text(theme.fg("muted", "─── Task ───"), 0, 0),
            );
            container.addChild(
              new Text(styleMultiline(theme, "dim", selected.task), 0, 0),
            );
            container.addChild(new Spacer(1));
            container.addChild(
              new Text(theme.fg("muted", "─── Live output ───"), 0, 0),
            );
            if (selected.errorMessage) {
              container.addChild(
                new Text(
                  styleMultiline(theme, "error", selected.errorMessage),
                  0,
                  0,
                ),
              );
            } else {
              const output = getFinalOutput(selected.messages);
              container.addChild(
                output
                  ? new Markdown(output.trim(), 0, 0, getMarkdownTheme())
                  : new Text(theme.fg("muted", "(waiting for output)"), 0, 0),
              );
            }
          }

          container.addChild(
            new Text(
              theme.fg("dim", "\u2191/\u2193 select \u00b7 enter/esc close"),
              0,
              0,
            ),
          );

          const innerWidth = Math.max(1, width - 4);
          return drawBox(container.render(innerWidth), width, border);
        },
        handleInput(data: string): void {
          const runs = listAgentRuns();
          if (matchesKey(data, Key.up)) {
            selectedIndex = Math.max(0, selectedIndex - 1);
            tui.requestRender();
            return;
          }
          if (matchesKey(data, Key.down)) {
            selectedIndex = Math.min(runs.length - 1, selectedIndex + 1);
            tui.requestRender();
            return;
          }
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
        width: "70%",
        minWidth: 50,
        maxHeight: "70%",
        margin: 1,
      },
    },
  );
}
