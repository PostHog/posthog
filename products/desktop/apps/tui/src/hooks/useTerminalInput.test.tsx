import { EventEmitter } from "node:events";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";
import type { MouseEvents } from "../mouse";
import { renderInTerminal } from "../testing";
import { useTerminalInput } from "./useTerminalInput";

describe("useTerminalInput", () => {
  it("hands a bare drop of file paths on as one key sequence, since pi's buffer would split it into keys", async () => {
    const folder = mkdtempSync(join(tmpdir(), "tui drop "));
    const png = join(folder, "shot.png");
    writeFileSync(png, "hi");
    const mouse: MouseEvents = new EventEmitter();
    const onKey = vi.fn();
    function Probe(): null {
      useTerminalInput(mouse, {
        onPress: () => {},
        onDrag: () => {},
        onRelease: () => {},
        onMove: () => {},
        onWheel: () => {},
        onKey,
      });
      return null;
    }
    const { instance } = renderInTerminal(<Probe />);
    await vi.waitFor(() => expect(mouse.listenerCount("keys")).toBe(1));

    const drop = `${png.replaceAll(" ", "\\ ")} ${png.replaceAll(" ", "\\ ")}`;
    mouse.emit("keys", drop);
    mouse.emit("keys", "ab");
    await new Promise((resolve) => setTimeout(resolve, 20));
    instance.unmount();

    expect(onKey.mock.calls.map(([sequence]) => sequence)).toEqual([
      drop,
      "a",
      "b",
    ]);
  });
});
