import type { BrowserWindow, WebContents, WebPreferences } from "electron";
import { beforeEach, describe, expect, it, vi } from "vitest";

const previewSession = vi.hoisted(() => ({
  setPermissionCheckHandler: vi.fn(),
  setPermissionRequestHandler: vi.fn(),
  on: vi.fn(),
}));

vi.mock("electron", () => ({
  session: { fromPartition: vi.fn(() => previewSession) },
}));
vi.mock("../external-links", () => ({ openExternalIfSafe: vi.fn() }));
vi.mock("../utils/logger", () => ({
  logger: { scope: () => ({ warn: vi.fn() }) },
}));

import {
  ARTIFACT_PREVIEW_ARG,
  ARTIFACT_PREVIEW_DATA_URL_PREFIX,
  TASK_PREVIEW_ARG,
  TASK_PREVIEW_PARTITION,
} from "../../shared/constants";
import { setupGuestWebviews } from "./electron-guest-webviews";

type Handler = (...args: never[]) => void;

function setup(allowLocalTaskPreviews: boolean): Map<string, Handler> {
  const handlers = new Map<string, Handler>();
  const window = {
    webContents: {
      on: vi.fn((event: string, handler: Handler) => {
        handlers.set(event, handler);
      }),
    },
  } as unknown as BrowserWindow;
  setupGuestWebviews(window, { allowLocalTaskPreviews });
  return handlers;
}

function attach(
  handlers: Map<string, Handler>,
  src: string,
  partition: string,
): { prevented: boolean; preferences: WebPreferences } {
  const preferences = { preload: "/guest-chosen.js" } as WebPreferences;
  const preventDefault = vi.fn();
  handlers.get("will-attach-webview")?.(
    { preventDefault } as never,
    preferences as never,
    { src, partition } as never,
  );
  return { prevented: preventDefault.mock.calls.length > 0, preferences };
}

describe("guest webviews", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it.each([
    {
      name: "a sandbox preview",
      src: "https://abc-123.modal.host/?_modal_connect_token=t",
      partition: TASK_PREVIEW_PARTITION,
      allowLocal: false,
      allowed: true,
    },
    {
      name: "a sandbox preview in another partition",
      src: "https://abc-123.modal.host/",
      partition: "persist:main",
      allowLocal: false,
      allowed: false,
    },
    {
      name: "an arbitrary site in the preview partition",
      src: "https://example.com/",
      partition: TASK_PREVIEW_PARTITION,
      allowLocal: true,
      allowed: false,
    },
    {
      name: "a plain http sandbox host",
      src: "http://abc-123.modal.host/",
      partition: TASK_PREVIEW_PARTITION,
      allowLocal: true,
      allowed: false,
    },
    {
      name: "a lookalike host",
      src: "https://modal.host.example.com/",
      partition: TASK_PREVIEW_PARTITION,
      allowLocal: false,
      allowed: false,
    },
    {
      name: "a local preview in a dev build",
      src: "http://localhost:50003/",
      partition: TASK_PREVIEW_PARTITION,
      allowLocal: true,
      allowed: true,
    },
    {
      name: "a local preview in a packaged build",
      src: "http://localhost:50003/",
      partition: TASK_PREVIEW_PARTITION,
      allowLocal: false,
      allowed: false,
    },
  ])(
    "attaches $name only when allowed",
    ({ src, partition, allowLocal, allowed }) => {
      const { prevented, preferences } = attach(
        setup(allowLocal),
        src,
        partition,
      );
      expect(prevented).toBe(!allowed);
      if (allowed) {
        expect(preferences).toMatchObject({
          preload: expect.stringMatching(/preload\.js$/),
          additionalArguments: [TASK_PREVIEW_ARG],
          sandbox: true,
          nodeIntegration: false,
          contextIsolation: true,
          webviewTag: false,
        });
      }
    },
  );

  it("gives an artifact preview its own preload", () => {
    const { prevented, preferences } = attach(
      setup(false),
      `${ARTIFACT_PREVIEW_DATA_URL_PREFIX}PGgxPlJlcG9ydDwvaDE+`,
      "artifact-preview-one",
    );
    expect(prevented).toBe(false);
    expect(preferences).toMatchObject({
      preload: expect.stringMatching(/preload\.js$/),
      additionalArguments: [ARTIFACT_PREVIEW_ARG],
      sandbox: true,
    });
  });

  it("keeps a task preview on sandbox hosts and denies its permissions", async () => {
    const { openExternalIfSafe } = await import("../external-links");
    const guestHandlers = new Map<string, Handler>();
    let windowOpenHandler: ((details: { url: string }) => unknown) | undefined;
    const guest = {
      session: previewSession,
      setWindowOpenHandler: vi.fn((handler) => {
        windowOpenHandler = handler;
      }),
      setWebRTCIPHandlingPolicy: vi.fn(),
      on: vi.fn((event: string, handler: Handler) => {
        guestHandlers.set(event, handler);
      }),
    } as unknown as WebContents;

    setup(false).get("did-attach-webview")?.({} as never, guest as never);

    const stayInPreview = vi.fn();
    guestHandlers.get("will-navigate")?.(
      { preventDefault: stayInPreview } as never,
      "https://abc-123.modal.host/settings" as never,
    );
    expect(stayInPreview).not.toHaveBeenCalled();

    const leavePreview = vi.fn();
    guestHandlers.get("will-navigate")?.(
      { preventDefault: leavePreview } as never,
      "https://accounts.example.com/login" as never,
    );
    expect(leavePreview).toHaveBeenCalledOnce();
    expect(openExternalIfSafe).toHaveBeenCalledWith(
      "https://accounts.example.com/login",
    );

    expect(windowOpenHandler?.({ url: "https://docs.example.com" })).toEqual({
      action: "deny",
    });
    const checkPermission =
      previewSession.setPermissionCheckHandler.mock.calls[0][0];
    expect(checkPermission()).toBe(false);
  });
});
