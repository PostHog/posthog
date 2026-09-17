import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  makeDeepLinkService,
  makeLogger,
  makeMainWindow,
} from "./link-test-helpers";
import {
  ScoutLinkEvent,
  type ScoutLinkPayload,
  ScoutLinkService,
} from "./scout-link";

describe("ScoutLinkService", () => {
  let deepLinkService: ReturnType<typeof makeDeepLinkService>;
  let mainWindow: ReturnType<typeof makeMainWindow>;
  let service: ScoutLinkService;

  beforeEach(() => {
    deepLinkService = makeDeepLinkService();
    mainWindow = makeMainWindow();
    service = new ScoutLinkService(deepLinkService, mainWindow, makeLogger());
  });

  it("registers a 'scout' handler on the DeepLinkService", () => {
    expect(deepLinkService.registerHandler).toHaveBeenCalledWith(
      "scout",
      expect.any(Function),
    );
  });

  it.each<{
    name: string;
    path: string;
    search: string;
    expected: ScoutLinkPayload;
  }>([
    {
      name: "emits OpenScout with the finding id from the query param",
      path: "error-tracking",
      search: "finding=abc-123",
      expected: { skillName: "error-tracking", findingId: "abc-123" },
    },
    {
      name: "emits OpenScout without a finding id when none is supplied",
      path: "error-tracking",
      search: "",
      expected: { skillName: "error-tracking", findingId: undefined },
    },
    {
      name: "takes only the first path segment as the skill name",
      path: "error-tracking/extra/segments",
      search: "",
      expected: { skillName: "error-tracking", findingId: undefined },
    },
    {
      name: "decodes a percent-encoded skill name",
      path: "error%2Dtracking",
      search: "",
      expected: { skillName: "error-tracking", findingId: undefined },
    },
  ])("$name", ({ path, search, expected }) => {
    const listener = vi.fn();
    service.on(ScoutLinkEvent.OpenScout, listener);

    const result = deepLinkService.trigger("scout", path, search);

    expect(result).toBe(true);
    expect(listener).toHaveBeenCalledWith(expected);
  });

  it("queues a pending deep link when no listener is attached", () => {
    deepLinkService.trigger("scout", "web-analytics", "finding=f-1");

    const pending = service.consumePendingDeepLink();
    expect(pending).toEqual({ skillName: "web-analytics", findingId: "f-1" });

    // Draining clears it
    expect(service.consumePendingDeepLink()).toBeNull();
  });

  it("returns false and does not emit when the path is empty", () => {
    const listener = vi.fn();
    service.on(ScoutLinkEvent.OpenScout, listener);

    const result = deepLinkService.trigger("scout", "");

    expect(result).toBe(false);
    expect(listener).not.toHaveBeenCalled();
  });

  it.each<{ name: string; minimized: boolean; expectRestore: boolean }>([
    {
      name: "focuses the main window on link arrival",
      minimized: false,
      expectRestore: false,
    },
    {
      name: "restores then focuses the main window when it is minimized",
      minimized: true,
      expectRestore: true,
    },
  ])("$name", ({ minimized, expectRestore }) => {
    mainWindow.isMinimized.mockReturnValue(minimized);

    deepLinkService.trigger("scout", "error-tracking");

    expect(mainWindow.focus).toHaveBeenCalledTimes(1);
    if (expectRestore) {
      expect(mainWindow.restore).toHaveBeenCalledTimes(1);
    } else {
      expect(mainWindow.restore).not.toHaveBeenCalled();
    }
  });
});
