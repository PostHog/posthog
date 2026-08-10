import { beforeEach, describe, expect, it, vi } from "vitest";

const mockOpenExternal = vi.hoisted(() => vi.fn(() => Promise.resolve()));
const mockWarn = vi.hoisted(() => vi.fn());

vi.mock("electron", () => ({
  shell: { openExternal: mockOpenExternal },
}));

vi.mock("./utils/logger.js", () => ({
  logger: {
    scope: () => ({
      info: vi.fn(),
      error: vi.fn(),
      warn: mockWarn,
      debug: vi.fn(),
    }),
  },
}));

import {
  setupExternalLinkHandlers,
  setupExternalLinkPermissionHandlers,
} from "./external-links";

type WindowOpenHandler = (details: { url: string }) => { action: string };
type WillNavigateHandler = (
  event: { preventDefault: () => void },
  url: string,
) => void;
type WillFrameNavigateHandler = (details: {
  preventDefault: () => void;
  isMainFrame: boolean;
  url: string;
}) => void;
type PermissionCheckHandler = (
  webContents: unknown,
  permission: string,
  requestingOrigin: string,
  details: { isMainFrame: boolean },
) => boolean;
type PermissionRequestHandler = (
  webContents: unknown,
  permission: string,
  callback: (permissionGranted: boolean) => void,
  details: Record<string, unknown>,
) => void;

// Packaged renderer served from a file: URL, and dev renderer from the Vite origin.
const PROD_HOME = new URL(
  "file:///Applications/PostHog.app/resources/renderer/main_window/index.html",
);
const DEV_HOME = new URL("http://localhost:5173");

function setup(appHome: URL) {
  let windowOpenHandler: WindowOpenHandler | undefined;
  let willNavigateHandler: WillNavigateHandler | undefined;
  let willFrameNavigateHandler: WillFrameNavigateHandler | undefined;
  const window = {
    webContents: {
      setWindowOpenHandler: (handler: WindowOpenHandler) => {
        windowOpenHandler = handler;
      },
      on: (
        event: string,
        handler: WillNavigateHandler | WillFrameNavigateHandler,
      ) => {
        if (event === "will-navigate") {
          willNavigateHandler = handler as WillNavigateHandler;
        }
        if (event === "will-frame-navigate") {
          willFrameNavigateHandler = handler as WillFrameNavigateHandler;
        }
      },
    },
  };
  setupExternalLinkHandlers(
    window as unknown as Parameters<typeof setupExternalLinkHandlers>[0],
    appHome,
  );
  if (!windowOpenHandler || !willNavigateHandler || !willFrameNavigateHandler) {
    throw new Error("Handlers were not registered");
  }
  return {
    windowOpenHandler,
    willNavigateHandler,
    willFrameNavigateHandler,
  };
}

function setupPermissionHandlers() {
  let permissionCheckHandler: PermissionCheckHandler | undefined;
  let permissionRequestHandler: PermissionRequestHandler | undefined;
  const session = {
    setPermissionCheckHandler: (handler: PermissionCheckHandler) => {
      permissionCheckHandler = handler;
    },
    setPermissionRequestHandler: (handler: PermissionRequestHandler) => {
      permissionRequestHandler = handler;
    },
  };

  setupExternalLinkPermissionHandlers(
    session as unknown as Parameters<
      typeof setupExternalLinkPermissionHandlers
    >[0],
  );
  if (!permissionCheckHandler || !permissionRequestHandler) {
    throw new Error("Permission handlers were not registered");
  }
  return { permissionCheckHandler, permissionRequestHandler };
}

const SAFE_URLS = [
  "https://posthog.com/docs",
  "http://example.com",
  "mailto:support@posthog.com",
];

// Schemes that dispatch to OS-registered handlers: smb/file enable NTLM
// credential theft on Windows, ms-msdt-class handlers take attacker args,
// and custom schemes deep-link into arbitrary installed apps.
const UNSAFE_URLS = [
  "smb://attacker.example/share",
  "file:///etc/passwd",
  "ms-msdt://id/PCWDiagnostic",
  "custom-scheme://payload",
  "javascript:alert(1)",
  "not a url",
];

beforeEach(() => {
  vi.clearAllMocks();
  mockOpenExternal.mockImplementation(() => Promise.resolve());
});

describe("external link policies", () => {
  describe("window open handler", () => {
    it.each(SAFE_URLS)("opens %s externally and denies the window", (url) => {
      const { windowOpenHandler } = setup(PROD_HOME);

      const result = windowOpenHandler({ url });

      expect(result).toEqual({ action: "deny" });
      expect(mockOpenExternal).toHaveBeenCalledExactlyOnceWith(url);
    });

    it.each(UNSAFE_URLS)("blocks %s without opening it", (url) => {
      const { windowOpenHandler } = setup(PROD_HOME);

      const result = windowOpenHandler({ url });

      expect(result).toEqual({ action: "deny" });
      expect(mockOpenExternal).not.toHaveBeenCalled();
      expect(mockWarn).toHaveBeenCalledOnce();
    });

    it("swallows an openExternal rejection instead of leaving it unhandled", async () => {
      mockOpenExternal.mockImplementationOnce(() =>
        Promise.reject(new Error("no handler")),
      );
      const { windowOpenHandler } = setup(PROD_HOME);

      windowOpenHandler({ url: "https://posthog.com" });
      await Promise.resolve();

      expect(mockWarn).toHaveBeenCalledOnce();
    });
  });

  describe("will-navigate (packaged, file: home)", () => {
    it.each([
      "file:///Applications/PostHog.app/resources/renderer/main_window/index.html",
      "file:///Applications/PostHog.app/resources/renderer/main_window/index.html#/tasks/1",
      "file:///Applications/PostHog.app/resources/renderer/main_window/index.html?source=reload",
    ])("treats renderer entry file %s as internal navigation", (url) => {
      const { willNavigateHandler } = setup(PROD_HOME);
      const preventDefault = vi.fn();

      willNavigateHandler({ preventDefault }, url);

      expect(preventDefault).not.toHaveBeenCalled();
      expect(mockOpenExternal).not.toHaveBeenCalled();
    });

    it.each([
      "file:///etc/passwd",
      "file:///Applications/PostHog.app/resources/renderer/other/index.html",
      "file:///Applications/PostHog.app/resources/renderer/main_window/assets/app.js",
      "file://attacker.example/Applications/PostHog.app/resources/renderer/main_window/index.html",
      "file:///Applications/PostHog.app/resources/renderer/main_window/index.html%2F..%2Fpayload.html",
    ])("blocks non-entry file %s without opening it externally", (url) => {
      const { willNavigateHandler } = setup(PROD_HOME);
      const preventDefault = vi.fn();

      willNavigateHandler({ preventDefault }, url);

      expect(preventDefault).toHaveBeenCalledOnce();
      expect(mockOpenExternal).not.toHaveBeenCalled();
      expect(mockWarn).toHaveBeenCalledOnce();
    });

    it("routes an external https link to the browser", () => {
      const { willNavigateHandler } = setup(PROD_HOME);
      const preventDefault = vi.fn();

      willNavigateHandler({ preventDefault }, "https://posthog.com");

      expect(preventDefault).toHaveBeenCalledOnce();
      expect(mockOpenExternal).toHaveBeenCalledExactlyOnceWith(
        "https://posthog.com",
      );
    });
  });

  describe("will-navigate (dev server, http: home)", () => {
    it.each(["http://localhost:5173/", "http://localhost:5173/sessions/42"])(
      "treats same-origin dev URL %s as internal navigation",
      (url) => {
        const { willNavigateHandler } = setup(DEV_HOME);
        const preventDefault = vi.fn();

        willNavigateHandler({ preventDefault }, url);

        expect(preventDefault).not.toHaveBeenCalled();
        expect(mockOpenExternal).not.toHaveBeenCalled();
      },
    );

    // Origin lookalikes must be handled as external URLs: userinfo resolving to
    // another host, a longer port, and a scheme change.
    it.each([
      "http://localhost:5173@evil.example/",
      "http://localhost:51730/",
      "https://localhost:5173/",
    ])("does not treat lookalike origin %s as internal", (url) => {
      const { willNavigateHandler } = setup(DEV_HOME);
      const preventDefault = vi.fn();

      willNavigateHandler({ preventDefault }, url);

      expect(preventDefault).toHaveBeenCalledOnce();
      expect(mockOpenExternal).toHaveBeenCalledExactlyOnceWith(url);
    });

    it("blocks an unsafe scheme in dev too", () => {
      const { willNavigateHandler } = setup(DEV_HOME);
      const preventDefault = vi.fn();

      willNavigateHandler({ preventDefault }, "file:///etc/passwd");

      expect(preventDefault).toHaveBeenCalledOnce();
      expect(mockOpenExternal).not.toHaveBeenCalled();
      expect(mockWarn).toHaveBeenCalledOnce();
    });
  });

  describe("will-frame-navigate (subframes)", () => {
    it.each([
      "mcp-sandbox://proxy",
      "about:blank",
      "about:srcdoc",
      "https://example.com/embed",
      "http://localhost:3000/embed",
      "blob:mcp-sandbox://proxy/1234",
      "data:text/html,<p>embedded</p>",
    ])("allows browser-contained navigation to %s", (url) => {
      const { willFrameNavigateHandler } = setup(PROD_HOME);
      const preventDefault = vi.fn();

      willFrameNavigateHandler({ preventDefault, isMainFrame: false, url });

      expect(preventDefault).not.toHaveBeenCalled();
      expect(mockOpenExternal).not.toHaveBeenCalled();
    });

    it.each([
      "smb://attacker.example/share",
      "file:///etc/passwd",
      "mailto:attacker@example.com",
      "custom-scheme://payload",
      "javascript:alert(1)",
      "not a url",
    ])("blocks external application navigation to %s", (url) => {
      const { willFrameNavigateHandler } = setup(PROD_HOME);
      const preventDefault = vi.fn();

      willFrameNavigateHandler({ preventDefault, isMainFrame: false, url });

      expect(preventDefault).toHaveBeenCalledOnce();
      expect(mockOpenExternal).not.toHaveBeenCalled();
      expect(mockWarn).toHaveBeenCalledOnce();
    });

    it("leaves main-frame navigation to the main-frame handler", () => {
      const { willFrameNavigateHandler } = setup(PROD_HOME);
      const preventDefault = vi.fn();

      willFrameNavigateHandler({
        preventDefault,
        isMainFrame: true,
        url: "custom-scheme://payload",
      });

      expect(preventDefault).not.toHaveBeenCalled();
      expect(mockWarn).not.toHaveBeenCalled();
    });
  });

  describe("session permission handlers", () => {
    it.each([
      { permission: "openExternal", expected: false },
      { permission: "media", expected: true },
    ])(
      "returns $expected for $permission permission checks and requests",
      ({ permission, expected }) => {
        const { permissionCheckHandler, permissionRequestHandler } =
          setupPermissionHandlers();
        const callback = vi.fn();

        expect(
          permissionCheckHandler(null, permission, "mcp-sandbox://proxy", {
            isMainFrame: false,
          }),
        ).toBe(expected);
        permissionRequestHandler({}, permission, callback, {});

        expect(callback).toHaveBeenCalledExactlyOnceWith(expected);
      },
    );
  });
});
