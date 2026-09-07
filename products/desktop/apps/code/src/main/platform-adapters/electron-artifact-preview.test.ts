import type { BrowserWindow, WebContents, WebPreferences } from "electron";
import { describe, expect, it, vi } from "vitest";
import {
  ARTIFACT_PREVIEW_ARG,
  ARTIFACT_PREVIEW_DATA_URL_PREFIX,
} from "../../shared/constants";
import {
  hardenArtifactPreviewPreferences,
  isAllowedArtifactPreview,
  lockDownArtifactPreview,
  setupArtifactPreviewWebviews,
} from "./electron-artifact-preview";

describe("artifact preview webviews", () => {
  it.each([
    ["https://example.com/report.html", "artifact-preview-one"],
    [`${ARTIFACT_PREVIEW_DATA_URL_PREFIX}<h1>report</h1>`, "persist:main"],
    ["file:///tmp/report.html", "artifact-preview-one"],
  ])("rejects unsupported source and partition pairs", (src, partition) => {
    expect(isAllowedArtifactPreview(src, partition)).toBe(false);
  });

  it("allows an HTML data document in an ephemeral artifact partition", () => {
    expect(
      isAllowedArtifactPreview(
        `${ARTIFACT_PREVIEW_DATA_URL_PREFIX}<script>render()</script>`,
        "artifact-preview-123",
      ),
    ).toBe(true);
  });

  it("overrides privileged guest preferences", () => {
    const preferences = {
      preload: "/tmp/untrusted.js",
      nodeIntegration: true,
      contextIsolation: false,
      sandbox: false,
      webSecurity: false,
      allowRunningInsecureContent: true,
      webviewTag: true,
      disableDialogs: false,
    } as WebPreferences;

    hardenArtifactPreviewPreferences(preferences, "/app/artifact-preload.js");

    expect(preferences).toMatchObject({
      preload: "/app/artifact-preload.js",
      additionalArguments: [ARTIFACT_PREVIEW_ARG],
      nodeIntegration: false,
      nodeIntegrationInSubFrames: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false,
      webviewTag: false,
      disableDialogs: true,
      experimentalFeatures: false,
      enableBlinkFeatures: "",
      plugins: false,
    });
  });

  it("blocks guest network, navigation, permissions, popups, and downloads", () => {
    const handlers = new Map<string, (...args: never[]) => void>();
    const permissionRequest = vi.fn();
    const permissionCheck = vi.fn();
    const beforeRequest = vi.fn();
    const download = vi.fn();
    const guest = {
      setWindowOpenHandler: vi.fn(),
      setWebRTCIPHandlingPolicy: vi.fn(),
      on: vi.fn((event: string, handler: (...args: never[]) => void) => {
        handlers.set(event, handler);
      }),
      session: {
        enableNetworkEmulation: vi.fn(),
        setProxy: vi.fn().mockResolvedValue(undefined),
        setPermissionCheckHandler: permissionCheck,
        setPermissionRequestHandler: permissionRequest,
        on: vi.fn((event: string, handler: (...args: never[]) => void) => {
          if (event === "will-download") download.mockImplementation(handler);
        }),
        webRequest: { onBeforeRequest: beforeRequest },
      },
    } as unknown as WebContents;

    lockDownArtifactPreview(guest);

    expect(guest.setWindowOpenHandler).toHaveBeenCalledOnce();
    expect(guest.setWebRTCIPHandlingPolicy).toHaveBeenCalledWith(
      "disable_non_proxied_udp",
    );
    expect(guest.session.enableNetworkEmulation).toHaveBeenCalledWith({
      offline: true,
    });
    expect(guest.session.setProxy).toHaveBeenCalledWith(
      expect.objectContaining({ mode: "fixed_servers" }),
    );
    expect(permissionCheck).toHaveBeenCalledOnce();
    expect(permissionRequest).toHaveBeenCalledOnce();
    expect(beforeRequest).toHaveBeenCalledWith(
      expect.objectContaining({
        urls: expect.arrayContaining(["http://*/*", "https://*/*"]),
      }),
      expect.any(Function),
    );

    const preventNavigation = vi.fn();
    handlers.get("will-navigate")?.(
      { preventDefault: preventNavigation } as never,
      "https://example.com" as never,
    );
    expect(preventNavigation).toHaveBeenCalledOnce();

    const allowNavigation = vi.fn();
    handlers.get("will-navigate")?.(
      { preventDefault: allowNavigation } as never,
      `${ARTIFACT_PREVIEW_DATA_URL_PREFIX}PGgxPlJlcG9ydDwvaDE+` as never,
    );
    handlers.get("will-navigate")?.(
      { preventDefault: allowNavigation } as never,
      "about:blank" as never,
    );
    expect(allowNavigation).not.toHaveBeenCalled();

    const preventSubframeNavigation = vi.fn();
    handlers.get("will-frame-navigate")?.({
      isMainFrame: false,
      preventDefault: preventSubframeNavigation,
    } as never);
    expect(preventSubframeNavigation).toHaveBeenCalledOnce();

    const allowMainFrameNavigation = vi.fn();
    handlers.get("will-frame-navigate")?.({
      isMainFrame: true,
      preventDefault: allowMainFrameNavigation,
    } as never);
    expect(allowMainFrameNavigation).not.toHaveBeenCalled();

    const preventDownload = vi.fn();
    download({ preventDefault: preventDownload });
    expect(preventDownload).toHaveBeenCalledOnce();
  });

  it("wires the attachment allowlist before locking down an allowed guest", () => {
    const handlers = new Map<string, (...args: never[]) => void>();
    const window = {
      webContents: {
        on: vi.fn((event: string, handler: (...args: never[]) => void) => {
          handlers.set(event, handler);
        }),
      },
    } as unknown as BrowserWindow;
    setupArtifactPreviewWebviews(window);

    const blockedPreferences = {} as WebPreferences;
    const preventBlocked = vi.fn();
    handlers.get("will-attach-webview")?.(
      { preventDefault: preventBlocked } as never,
      blockedPreferences as never,
      {
        src: "https://example.com",
        partition: "artifact-preview-one",
      } as never,
    );
    expect(preventBlocked).toHaveBeenCalledOnce();
    expect(blockedPreferences.preload).toBeUndefined();

    const allowedPreferences = {} as WebPreferences;
    const preventAllowed = vi.fn();
    handlers.get("will-attach-webview")?.(
      { preventDefault: preventAllowed } as never,
      allowedPreferences as never,
      {
        src: `${ARTIFACT_PREVIEW_DATA_URL_PREFIX}PGgxPlJlcG9ydDwvaDE+`,
        partition: "artifact-preview-one",
      } as never,
    );
    expect(preventAllowed).not.toHaveBeenCalled();
    expect(allowedPreferences).toMatchObject({
      preload: expect.stringMatching(/preload\.js$/),
      additionalArguments: [ARTIFACT_PREVIEW_ARG],
      sandbox: true,
    });

    const guest = {
      setWindowOpenHandler: vi.fn(),
      setWebRTCIPHandlingPolicy: vi.fn(),
      on: vi.fn(),
      session: {
        enableNetworkEmulation: vi.fn(),
        setProxy: vi.fn().mockResolvedValue(undefined),
        setPermissionCheckHandler: vi.fn(),
        setPermissionRequestHandler: vi.fn(),
        on: vi.fn(),
        webRequest: { onBeforeRequest: vi.fn() },
      },
    } as unknown as WebContents;
    handlers.get("did-attach-webview")?.({} as never, guest as never);
    expect(guest.setWindowOpenHandler).toHaveBeenCalledOnce();
  });
});
