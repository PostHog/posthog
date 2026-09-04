import { CANVAS_V2_FRAME_NAME } from "@posthog/shared";
import { describe, expect, it, vi } from "vitest";

vi.mock("./utils/logger.js", () => ({
  logger: {
    scope: () => ({
      info: vi.fn(),
      error: vi.fn(),
      warn: vi.fn(),
      debug: vi.fn(),
    }),
  },
}));

import {
  guardCanvasFrameNavigation,
  installCanvasFrameEgressGuard,
  isAllowedBoardFrameRequest,
} from "./canvas-frame-egress";

const board = { name: CANVAS_V2_FRAME_NAME };

describe("canvas frame egress", () => {
  describe("isAllowedBoardFrameRequest", () => {
    it.each([
      "https://evil.example/?data=secret",
      "https://esm.sh/react@19.0.0",
      "https://esm.sh/" + "c2VjcmV0",
      "http://127.0.0.1:8000/",
      "wss://evil.example/socket",
      "https://cdn.jsdelivr.net/npm/left-pad@1.0.0",
      "https://app.posthog.com/api/projects/1/query/",
    ])("blocks %s from the board frame", (url) => {
      expect(isAllowedBoardFrameRequest({ url, frame: board })).toBe(false);
    });

    it.each([
      [undefined],
      [null],
      [{ name: "" }],
      [{ name: "mcp-app" }],
    ] as const)("leaves other frames alone (%o)", (frame) => {
      expect(
        isAllowedBoardFrameRequest({ url: "https://evil.example/x", frame }),
      ).toBe(true);
    });
  });

  it("cancels a blocked request and passes an allowed one", () => {
    let listener: Parameters<
      Parameters<typeof installCanvasFrameEgressGuard>[0]["onBeforeRequest"]
    >[1] = () => undefined;
    installCanvasFrameEgressGuard({
      onBeforeRequest: (_filter, given) => {
        listener = given;
      },
    });

    const blocked = vi.fn();
    listener(
      { url: "https://evil.example/?d=1", resourceType: "image", frame: board },
      blocked,
    );
    expect(blocked).toHaveBeenCalledWith({ cancel: true });

    const allowed = vi.fn();
    listener(
      {
        url: "https://app.posthog.com/api/projects/1/query/",
        resourceType: "xhr",
        frame: { name: "" },
      },
      allowed,
    );
    expect(allowed).toHaveBeenCalledWith({});
  });

  it("stops the board frame from navigating itself out", () => {
    let listener: (details: {
      url: string;
      frame?: { name?: string } | null;
      preventDefault: () => void;
    }) => void = () => undefined;
    guardCanvasFrameNavigation({
      on: (_event, given) => {
        listener = given;
      },
    });

    const leaving = vi.fn();
    listener({
      url: "https://evil.example/?d=secret",
      frame: board,
      preventDefault: leaving,
    });
    expect(leaving).toHaveBeenCalledTimes(1);

    const reload = vi.fn();
    listener({ url: "about:srcdoc", frame: board, preventDefault: reload });
    expect(reload).not.toHaveBeenCalled();

    const other = vi.fn();
    listener({
      url: "https://posthog.com/docs",
      frame: { name: "other" },
      preventDefault: other,
    });
    expect(other).not.toHaveBeenCalled();
  });
});
