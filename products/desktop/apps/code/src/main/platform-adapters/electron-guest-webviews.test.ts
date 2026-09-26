import type { BrowserWindow, WebContents, WebPreferences } from "electron";
import { beforeEach, describe, expect, it, vi } from "vitest";

const previewSession = vi.hoisted(() => ({
  setPermissionCheckHandler: vi.fn(),
  setPermissionRequestHandler: vi.fn(),
  on: vi.fn(),
  webRequest: { onBeforeRequest: vi.fn() },
}));

vi.mock("electron", () => ({
  session: { fromPartition: vi.fn(() => previewSession) },
  webContents: { fromId: vi.fn() },
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
import {
  authorizeTaskPreview,
  isBlockedPreviewRequest,
} from "./electron-task-preview";

type Handler = (...args: never[]) => void;

function setup(): Map<string, Handler> {
  const handlers = new Map<string, Handler>();
  const window = {
    webContents: {
      on: vi.fn((event: string, handler: Handler) => {
        handlers.set(event, handler);
      }),
    },
  } as unknown as BrowserWindow;
  setupGuestWebviews(window);
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
      src: "https://abc-123.modal.host/",
      partition: TASK_PREVIEW_PARTITION,
      allowed: true,
    },
    {
      name: "a sandbox preview with its token in the URL",
      src: "https://abc-123.modal.host/?_modal_connect_token=t",
      partition: TASK_PREVIEW_PARTITION,
      allowed: false,
    },
    {
      name: "a sandbox preview in another partition",
      src: "https://abc-123.modal.host/",
      partition: "persist:main",
      allowed: false,
    },
    {
      name: "an arbitrary site in the preview partition",
      src: "https://example.com/",
      partition: TASK_PREVIEW_PARTITION,
      allowed: false,
    },
    {
      name: "a plain http sandbox host",
      src: "http://abc-123.modal.host/",
      partition: TASK_PREVIEW_PARTITION,
      allowed: false,
    },
    {
      name: "a lookalike host",
      src: "https://modal.host.example.com/",
      partition: TASK_PREVIEW_PARTITION,
      allowed: false,
    },
    {
      name: "a server on this computer",
      src: "http://localhost:5173/",
      partition: TASK_PREVIEW_PARTITION,
      allowed: true,
    },
    {
      name: "a loopback address",
      src: "http://127.0.0.1:3000/",
      partition: TASK_PREVIEW_PARTITION,
      allowed: true,
    },
    {
      name: "a plain http host on the network",
      src: "http://192.168.1.10:3000/",
      partition: TASK_PREVIEW_PARTITION,
      allowed: false,
    },
  ])("attaches $name only when allowed", ({ src, partition, allowed }) => {
    const { prevented, preferences } = attach(setup(), src, partition);
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
  });

  it("gives an artifact preview its own preload", () => {
    const { prevented, preferences } = attach(
      setup(),
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

    setup().get("did-attach-webview")?.({} as never, guest as never);
    guestHandlers.get("did-start-navigation")?.({
      url: "https://abc-123.modal.host/",
      isMainFrame: true,
    } as never);

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

    const otherSandbox = vi.fn();
    guestHandlers.get("will-navigate")?.(
      { preventDefault: otherSandbox } as never,
      "https://other-456.modal.host/" as never,
    );
    expect(otherSandbox).toHaveBeenCalledOnce();

    const crossOriginRedirect = vi.fn();
    guestHandlers.get("will-redirect")?.(
      { preventDefault: crossOriginRedirect, isMainFrame: true } as never,
      "http://localhost:8000/admin" as never,
    );
    expect(crossOriginRedirect).toHaveBeenCalledOnce();

    expect(windowOpenHandler?.({ url: "https://docs.example.com" })).toEqual({
      action: "deny",
    });
    const checkPermission =
      previewSession.setPermissionCheckHandler.mock.calls[0][0];
    expect(checkPermission()).toBe(false);
  });

  it.each([
    ["localhost", "https://a.modal.host/", "http://localhost:8000/", true],
    [
      "a loopback address",
      "https://a.modal.host/",
      "http://127.0.0.1:5432/",
      true,
    ],
    ["an IPv6 loopback", "https://a.modal.host/", "http://[::1]:3000/", true],
    ["a home router", "https://a.modal.host/", "http://192.168.1.1/", true],
    ["a private network", "https://a.modal.host/", "ws://10.0.0.5:9000/", true],
    [
      "cloud metadata",
      "https://a.modal.host/",
      "http://169.254.169.254/",
      true,
    ],
    ["a file", "https://a.modal.host/", "file:///etc/passwd", true],
    [
      "a public site",
      "https://a.modal.host/",
      "https://cdn.example.com/a.js",
      false,
    ],
    [
      "its own sandbox",
      "https://a.modal.host/",
      "wss://a.modal.host/hmr",
      false,
    ],
    [
      "a local preview's own server",
      "http://localhost:5173/",
      "http://localhost:5173/src/main.tsx",
      false,
    ],
  ])(
    "blocks a request from a preview to %s only when unsafe",
    (_name, pageUrl, requestUrl, blocked) => {
      expect(isBlockedPreviewRequest(pageUrl, requestUrl)).toBe(blocked);
    },
  );

  it("moves the sandbox token into an http-only cookie", async () => {
    const cookies = { set: vi.fn(async () => undefined) };

    await expect(
      authorizeTaskPreview(
        "https://abc-123.modal.host/?_modal_connect_token=secret",
        cookies,
      ),
    ).resolves.toBe("https://abc-123.modal.host/");
    expect(cookies.set).toHaveBeenCalledWith({
      url: "https://abc-123.modal.host",
      name: "_modal_connect_token",
      value: "secret",
      path: "/",
      secure: true,
      httpOnly: true,
      sameSite: "strict",
    });

    await expect(
      authorizeTaskPreview(
        "https://evil.example.com/?_modal_connect_token=secret",
        cookies,
      ),
    ).resolves.toBeNull();
    await expect(
      authorizeTaskPreview(
        "http://localhost:3000/?_modal_connect_token=secret",
        cookies,
      ),
    ).resolves.toBeNull();
    expect(cookies.set).toHaveBeenCalledOnce();
  });
});
