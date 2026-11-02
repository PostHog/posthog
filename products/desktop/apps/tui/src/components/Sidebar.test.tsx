import { createRequire } from "node:module";
import { dirname } from "node:path";
import { renderToString } from "ink";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import type { SidebarRow } from "../sidebar";
import { Sidebar } from "./Sidebar";

const row = (
  title: string,
  indicator: "waiting" | "alive" | "working" | "failed",
  local = false,
): SidebarRow => ({
  kind: "task",
  taskId: title,
  paneId: null,
  title,
  indicator,
  local,
  nested: false,
});

// Whether faint text is on where the given text is first drawn.
const dimAt = (output: string, text: string): boolean => {
  const before = output.slice(0, output.indexOf(text));
  const codes = [...before.matchAll(new RegExp(`${"\u001b"}\\[(2|22)m`, "g"))];
  return codes.at(-1)?.[1] === "2";
};

describe("Sidebar", () => {
  // Tests have no terminal, so Ink's own chalk draws no styles; a real terminal gets full colour.
  let chalk: { level: number };
  let level = 0;
  beforeAll(async () => {
    const require = createRequire(import.meta.url);
    const path = require.resolve("chalk", {
      paths: [dirname(require.resolve("ink"))],
    });
    chalk = (await import(path)).default;
    level = chalk.level;
    chalk.level = 3;
  });
  afterAll(() => {
    chalk.level = level;
  });

  it("keeps every row at full strength when the sidebar loses focus", () => {
    const output = renderToString(
      <Sidebar
        notice={null}
        rows={[
          row("Done", "waiting"),
          row("Quiet", "alive"),
          row("Busy", "working"),
        ]}
        focused={false}
        selectedIndex={0}
        activePaneId={null}
      />,
      { columns: 40 },
    );

    const [done, quiet, busy] = output.split("\n");
    expect(output).not.toContain("✗");
    expect(dimAt(done, "Done")).toBe(false);
    expect(dimAt(quiet, "●")).toBe(false);
    expect(dimAt(busy, "⠋")).toBe(false);
    expect(dimAt(busy, "Busy")).toBe(false);
  });

  it("marks a failed chat with a cross, since its run cannot be picked up again", () => {
    const output = renderToString(
      <Sidebar
        notice={null}
        rows={[row("Broken", "failed"), row("Local broken", "failed", true)]}
        focused
        selectedIndex={0}
        activePaneId={null}
      />,
      { columns: 40 },
    );
    const [cloud, local] = output.split("\n");
    expect(cloud).toContain("✗");
    expect(local).toContain("✗");
    expect(output).not.toContain("●");
  });
});
