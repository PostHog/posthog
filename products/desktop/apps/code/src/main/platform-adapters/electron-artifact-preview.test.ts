import type { WebContents, WebPreferences } from "electron";
import { describe, expect, it, vi } from "vitest";
import { ARTIFACT_PREVIEW_ARG } from "../../shared/constants";
import {
  ARTIFACT_PREVIEW_DATA_URL_PREFIX,
  hardenArtifactPreviewPreferences,
  isAllowedArtifactPreview,
  lockDownArtifactPreview,
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
      on: vi.fn((event: string, handler: (...args: never[]) => void) => {
        handlers.set(event, handler);
      }),
      session: {
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

    const preventDownload = vi.fn();
    download({ preventDefault: preventDownload });
    expect(preventDownload).toHaveBeenCalledOnce();
  });
});
