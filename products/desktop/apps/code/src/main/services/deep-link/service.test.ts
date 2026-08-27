import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockAppLifecycle = vi.hoisted(() => ({
  whenReady: vi.fn().mockResolvedValue(undefined),
  quit: vi.fn(),
  exit: vi.fn(),
  onQuit: vi.fn(() => () => {}),
  registerDeepLinkScheme: vi.fn(),
}));

vi.mock("../../utils/logger.js", () => ({
  logger: {
    scope: () => ({
      info: vi.fn(),
      error: vi.fn(),
      warn: vi.fn(),
      debug: vi.fn(),
    }),
  },
}));

import type { IAppLifecycle } from "@posthog/platform/app-lifecycle";
import { DeepLinkService } from "./service";

describe("DeepLinkService", () => {
  let service: DeepLinkService;
  const originalIsDev = process.env.POSTHOG_CODE_IS_DEV;

  beforeEach(() => {
    vi.clearAllMocks();
    process.env.POSTHOG_CODE_IS_DEV = "false";
    service = new DeepLinkService(mockAppLifecycle as unknown as IAppLifecycle);
  });

  afterEach(() => {
    if (originalIsDev === undefined) {
      delete process.env.POSTHOG_CODE_IS_DEV;
    } else {
      process.env.POSTHOG_CODE_IS_DEV = originalIsDev;
    }
  });

  describe("registerProtocol", () => {
    it("registers posthog-code and legacy protocols in production", () => {
      process.env.POSTHOG_CODE_IS_DEV = "false";

      service.registerProtocol();

      expect(mockAppLifecycle.registerDeepLinkScheme).toHaveBeenCalledWith(
        "posthog-code",
      );
      expect(mockAppLifecycle.registerDeepLinkScheme).toHaveBeenCalledWith(
        "twig",
      );
      expect(mockAppLifecycle.registerDeepLinkScheme).toHaveBeenCalledWith(
        "array",
      );
      expect(mockAppLifecycle.registerDeepLinkScheme).toHaveBeenCalledTimes(3);
    });

    it("registers posthog-code-dev only in development mode", () => {
      process.env.POSTHOG_CODE_IS_DEV = "true";

      service.registerProtocol();

      expect(mockAppLifecycle.registerDeepLinkScheme).toHaveBeenCalledWith(
        "posthog-code-dev",
      );
      expect(mockAppLifecycle.registerDeepLinkScheme).toHaveBeenCalledTimes(1);
    });

    it("prevents multiple registrations", () => {
      process.env.POSTHOG_CODE_IS_DEV = "false";

      service.registerProtocol();
      service.registerProtocol();

      expect(mockAppLifecycle.registerDeepLinkScheme).toHaveBeenCalledTimes(3);
    });
  });

  describe("registerHandler", () => {
    it("registers a handler for a key", () => {
      const handler = vi.fn(() => true);

      service.registerHandler("task", handler);

      const result = service.handleUrl("posthog-code://task/123");
      expect(handler).toHaveBeenCalledWith("123", expect.any(URLSearchParams));
      expect(result).toBe(true);
    });

    it("overwrites existing handler for same key", () => {
      const handler1 = vi.fn(() => true);
      const handler2 = vi.fn(() => false);

      service.registerHandler("task", handler1);
      service.registerHandler("task", handler2);

      service.handleUrl("posthog-code://task/123");
      expect(handler1).not.toHaveBeenCalled();
      expect(handler2).toHaveBeenCalled();
    });
  });

  describe("unregisterHandler", () => {
    it("removes a registered handler", () => {
      const handler = vi.fn(() => true);
      service.registerHandler("task", handler);

      service.unregisterHandler("task");

      const result = service.handleUrl("posthog-code://task/123");
      expect(handler).not.toHaveBeenCalled();
      expect(result).toBe(false);
    });

    it("does not throw when unregistering non-existent handler", () => {
      expect(() => service.unregisterHandler("nonexistent")).not.toThrow();
    });
  });

  describe("handleUrl", () => {
    beforeEach(() => {
      service.registerHandler("task", (path, _params) => {
        return path.length > 0;
      });
      service.registerHandler("oauth", () => true);
    });

    describe("posthog-code:// protocol", () => {
      it("handles posthog-code:// URLs", () => {
        const handler = vi.fn(() => true);
        service.registerHandler("test", handler);

        const result = service.handleUrl("posthog-code://test/foo");
        expect(result).toBe(true);
        expect(handler).toHaveBeenCalledWith(
          "foo",
          expect.any(URLSearchParams),
        );
      });

      it("passes path segments to handler", () => {
        const handler = vi.fn(() => true);
        service.registerHandler("task", handler);

        service.handleUrl("posthog-code://task/abc123/details");
        expect(handler).toHaveBeenCalledWith(
          "abc123/details",
          expect.any(URLSearchParams),
        );
      });

      it("passes query parameters to handler", () => {
        const handler = vi.fn((_path, params) => {
          expect(params.get("token")).toBe("secret");
          expect(params.get("redirect")).toBe("home");
          return true;
        });
        service.registerHandler("auth", handler);

        service.handleUrl(
          "posthog-code://auth/callback?token=secret&redirect=home",
        );
        expect(handler).toHaveBeenCalled();
      });

      it("handles empty path", () => {
        const handler = vi.fn(() => true);
        service.registerHandler("ping", handler);

        service.handleUrl("posthog-code://ping");
        expect(handler).toHaveBeenCalledWith("", expect.any(URLSearchParams));
      });
    });

    describe("twig:// protocol (legacy)", () => {
      it("handles twig:// URLs for backwards compatibility", () => {
        const handler = vi.fn(() => true);
        service.registerHandler("task", handler);

        const result = service.handleUrl("twig://task/123");
        expect(result).toBe(true);
        expect(handler).toHaveBeenCalledWith(
          "123",
          expect.any(URLSearchParams),
        );
      });

      it("works identically to posthog-code:// protocol", () => {
        const handler = vi.fn(() => true);
        service.registerHandler("oauth", handler);

        service.handleUrl("twig://oauth/callback?code=abc");
        expect(handler).toHaveBeenCalledWith(
          "callback",
          expect.any(URLSearchParams),
        );
      });
    });

    describe("array:// protocol (legacy)", () => {
      it("handles array:// URLs for backwards compatibility", () => {
        const handler = vi.fn(() => true);
        service.registerHandler("callback", handler);

        const result = service.handleUrl("array://callback?code=abc");
        expect(result).toBe(true);
        expect(handler).toHaveBeenCalledWith("", expect.any(URLSearchParams));
      });
    });

    describe("error handling", () => {
      it("returns false for non-matching protocols", () => {
        expect(service.handleUrl("https://example.com")).toBe(false);
        expect(service.handleUrl("myapp://task/123")).toBe(false);
        expect(service.handleUrl("file:///path/to/file")).toBe(false);
      });

      it("returns false for URLs without main key", () => {
        expect(service.handleUrl("posthog-code://")).toBe(false);
      });

      it("returns false for unregistered handlers", () => {
        const result = service.handleUrl("posthog-code://unknown/path");
        expect(result).toBe(false);
      });

      it("returns false for malformed URLs", () => {
        expect(service.handleUrl("posthog-code://[invalid")).toBe(false);
      });

      it("returns handler result when handler returns false", () => {
        service.registerHandler("failing", () => false);
        const result = service.handleUrl("posthog-code://failing/test");
        expect(result).toBe(false);
      });
    });

    describe("primary protocol by build", () => {
      it("accepts posthog-code-dev:// in development", () => {
        process.env.POSTHOG_CODE_IS_DEV = "true";
        const handler = vi.fn(() => true);
        service.registerHandler("inbox", handler);

        const result = service.handleUrl("posthog-code-dev://inbox/r1");
        expect(result).toBe(true);
        expect(handler).toHaveBeenCalledWith("r1", expect.any(URLSearchParams));
      });

      it("rejects posthog-code:// in development", () => {
        process.env.POSTHOG_CODE_IS_DEV = "true";
        service.registerHandler(
          "inbox",
          vi.fn(() => true),
        );

        expect(service.handleUrl("posthog-code://inbox/r1")).toBe(false);
      });

      it("rejects posthog-code-dev:// in production", () => {
        process.env.POSTHOG_CODE_IS_DEV = "false";
        service.registerHandler(
          "inbox",
          vi.fn(() => true),
        );

        expect(service.handleUrl("posthog-code-dev://inbox/r1")).toBe(false);
      });
    });
  });

  describe("getProtocol", () => {
    it("returns posthog-code in production", () => {
      process.env.POSTHOG_CODE_IS_DEV = "false";
      expect(service.getProtocol()).toBe("posthog-code");
    });

    it("returns posthog-code-dev in development", () => {
      process.env.POSTHOG_CODE_IS_DEV = "true";
      expect(service.getProtocol()).toBe("posthog-code-dev");
    });
  });
});
