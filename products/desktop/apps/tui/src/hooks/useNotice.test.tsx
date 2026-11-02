import { afterEach, describe, expect, it, vi } from "vitest";
import { renderInTerminal } from "../testing";
import { type Notice, useNotice } from "./useNotice";

describe("useNotice", () => {
  afterEach(() => vi.useRealTimers());

  it("keeps a newer notice up when an older notice's time runs out", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    let current: Notice | undefined;
    function Probe(): null {
      current = useNotice();
      return null;
    }
    const { instance } = renderInTerminal(<Probe />);

    current?.flashNotice("first");
    await vi.advanceTimersByTimeAsync(6_000);
    current?.flashNotice("second");
    await vi.advanceTimersByTimeAsync(4_000);
    try {
      await vi.waitFor(() => expect(current?.shown?.text).toBe("second"));
    } finally {
      instance.unmount();
    }
  });
});
