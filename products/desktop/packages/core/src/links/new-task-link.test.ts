import type { IDeepLinkRegistry } from "@posthog/platform/deep-link";
import type { IMainWindow } from "@posthog/platform/main-window";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NewTaskLinkEvent, NewTaskLinkService } from "./new-task-link";

function makeLogger() {
  const logger = {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
    scope: vi.fn(() => logger),
  };
  return logger;
}

function createMockDeepLinkService() {
  const handlers = new Map<
    string,
    (path: string, params: URLSearchParams) => boolean
  >();
  return {
    registerHandler: vi.fn((key, handler) => handlers.set(key, handler)),
    _handlers: handlers,
    _invoke(key: string, params: URLSearchParams) {
      const handler = handlers.get(key);
      if (!handler) throw new Error(`No handler for key: ${key}`);
      return handler("", params);
    },
  };
}

function createMockMainWindow(): IMainWindow {
  return {
    isMinimized: vi.fn(() => false),
    restore: vi.fn(),
    focus: vi.fn(),
    close: vi.fn(),
    show: vi.fn(),
    hide: vi.fn(),
    minimize: vi.fn(),
    maximize: vi.fn(),
    unmaximize: vi.fn(),
    isMaximized: vi.fn(() => false),
    isVisible: vi.fn(() => true),
    setTitle: vi.fn(),
    loadURL: vi.fn(),
    webContents: {} as never,
    on: vi.fn(),
    once: vi.fn(),
    removeListener: vi.fn(),
  } as unknown as IMainWindow;
}

describe("NewTaskLinkService", () => {
  let service: NewTaskLinkService;
  let mockDeepLink: ReturnType<typeof createMockDeepLinkService>;
  let mockWindow: IMainWindow;

  beforeEach(() => {
    vi.clearAllMocks();
    mockDeepLink = createMockDeepLinkService();
    mockWindow = createMockMainWindow();
    service = new NewTaskLinkService(
      mockDeepLink as unknown as IDeepLinkRegistry,
      mockWindow,
      makeLogger(),
    );
  });

  describe("constructor", () => {
    it("registers handlers for new, plan and issue", () => {
      expect(mockDeepLink.registerHandler).toHaveBeenCalledWith(
        "new",
        expect.any(Function),
      );
      expect(mockDeepLink.registerHandler).toHaveBeenCalledWith(
        "plan",
        expect.any(Function),
      );
      expect(mockDeepLink.registerHandler).toHaveBeenCalledWith(
        "issue",
        expect.any(Function),
      );
      expect(mockDeepLink.registerHandler).toHaveBeenCalledTimes(3);
    });
  });

  describe("handleNew", () => {
    it("rejects empty params", () => {
      const result = mockDeepLink._invoke("new", new URLSearchParams());
      expect(result).toBe(false);
    });

    it("rejects when only mode is provided", () => {
      const result = mockDeepLink._invoke(
        "new",
        new URLSearchParams("mode=plan"),
      );
      expect(result).toBe(false);
    });

    it("rejects when only model is provided", () => {
      const result = mockDeepLink._invoke(
        "new",
        new URLSearchParams("model=opus"),
      );
      expect(result).toBe(false);
    });

    it("rejects when only mode and model are provided", () => {
      const result = mockDeepLink._invoke(
        "new",
        new URLSearchParams("mode=plan&model=opus"),
      );
      expect(result).toBe(false);
    });

    it("accepts prompt only", () => {
      const listener = vi.fn();
      service.on(NewTaskLinkEvent.Action, listener);

      const result = mockDeepLink._invoke(
        "new",
        new URLSearchParams("prompt=hello+world"),
      );

      expect(result).toBe(true);
      expect(listener).toHaveBeenCalledWith(
        expect.objectContaining({
          action: "new",
          prompt: "hello world",
        }),
      );
    });

    it("accepts repo only", () => {
      const listener = vi.fn();
      service.on(NewTaskLinkEvent.Action, listener);

      const result = mockDeepLink._invoke(
        "new",
        new URLSearchParams("repo=posthog/posthog"),
      );

      expect(result).toBe(true);
      expect(listener).toHaveBeenCalledWith(
        expect.objectContaining({
          action: "new",
          repo: "posthog/posthog",
          prompt: undefined,
        }),
      );
    });

    it("passes shared params (repo, mode, model)", () => {
      const listener = vi.fn();
      service.on(NewTaskLinkEvent.Action, listener);

      mockDeepLink._invoke(
        "new",
        new URLSearchParams("prompt=test&repo=org/repo&mode=cloud&model=opus"),
      );

      expect(listener).toHaveBeenCalledWith({
        action: "new",
        prompt: "test",
        repo: "org/repo",
        mode: "cloud",
        model: "opus",
      });
    });
  });

  describe("handlePlan", () => {
    it("rejects missing plan param", () => {
      const result = mockDeepLink._invoke(
        "plan",
        new URLSearchParams("repo=org/repo"),
      );
      expect(result).toBe(false);
    });

    it("rejects invalid base64", () => {
      const result = mockDeepLink._invoke(
        "plan",
        new URLSearchParams("plan=!!!invalid-base64!!!"),
      );
      expect(result).toBe(false);
    });

    it("accepts valid base64 plan", () => {
      const listener = vi.fn();
      service.on(NewTaskLinkEvent.Action, listener);

      const planText = "# My Plan\n\n1. Do thing\n2. Do other thing";
      const encoded = btoa(planText);

      const result = mockDeepLink._invoke(
        "plan",
        new URLSearchParams(`plan=${encoded}&repo=org/repo`),
      );

      expect(result).toBe(true);
      expect(listener).toHaveBeenCalledWith(
        expect.objectContaining({
          action: "plan",
          plan: planText,
          repo: "org/repo",
        }),
      );
    });

    it("accepts URL-safe base64 with - and _ instead of + and /", () => {
      const listener = vi.fn();
      service.on(NewTaskLinkEvent.Action, listener);

      // "??>" base64 is "Pz8+" — contains `+` so URL-safe substitutes to `-`.
      const planText = "??>";
      const standard = Buffer.from(planText, "utf-8").toString("base64");
      const urlSafe = standard
        .replace(/\+/g, "-")
        .replace(/\//g, "_")
        .replace(/=+$/, "");

      const result = mockDeepLink._invoke(
        "plan",
        new URLSearchParams(`plan=${urlSafe}`),
      );

      expect(result).toBe(true);
      expect(listener).toHaveBeenCalledWith(
        expect.objectContaining({ action: "plan", plan: planText }),
      );
    });

    it("recovers when + was decoded to space by URLSearchParams", () => {
      const listener = vi.fn();
      service.on(NewTaskLinkEvent.Action, listener);

      // "Pz8+" arrives as "Pz8 " because URLSearchParams turns + into space.
      const result = mockDeepLink._invoke(
        "plan",
        new URLSearchParams("plan=Pz8+"),
      );

      expect(result).toBe(true);
      expect(listener).toHaveBeenCalledWith(
        expect.objectContaining({ action: "plan", plan: "??>" }),
      );
    });

    it("round-trips UTF-8 (emoji, non-ASCII)", () => {
      const listener = vi.fn();
      service.on(NewTaskLinkEvent.Action, listener);

      const planText = "Plan 🚀: café — naïve résumé";
      const encoded = Buffer.from(planText, "utf-8").toString("base64");

      const result = mockDeepLink._invoke(
        "plan",
        new URLSearchParams(`plan=${encoded}`),
      );

      expect(result).toBe(true);
      expect(listener).toHaveBeenCalledWith(
        expect.objectContaining({ action: "plan", plan: planText }),
      );
    });

    it("passes shared params", () => {
      const listener = vi.fn();
      service.on(NewTaskLinkEvent.Action, listener);

      const encoded = btoa("plan content");
      mockDeepLink._invoke(
        "plan",
        new URLSearchParams(`plan=${encoded}&mode=worktree&model=sonnet`),
      );

      expect(listener).toHaveBeenCalledWith(
        expect.objectContaining({
          mode: "worktree",
          model: "sonnet",
        }),
      );
    });
  });

  describe("handleIssue", () => {
    it("rejects missing url param", () => {
      const result = mockDeepLink._invoke("issue", new URLSearchParams());
      expect(result).toBe(false);
    });

    it("rejects non-GitHub URLs", () => {
      const result = mockDeepLink._invoke(
        "issue",
        new URLSearchParams("url=https://gitlab.com/org/repo/issues/1"),
      );
      expect(result).toBe(false);
    });

    it("rejects GitHub URLs that are not issues", () => {
      const result = mockDeepLink._invoke(
        "issue",
        new URLSearchParams("url=https://github.com/org/repo/pull/1"),
      );
      expect(result).toBe(false);
    });

    it("rejects issue URLs with non-numeric issue number", () => {
      const result = mockDeepLink._invoke(
        "issue",
        new URLSearchParams("url=https://github.com/org/repo/issues/abc"),
      );
      expect(result).toBe(false);
    });

    it("rejects issue URLs with extra trailing path segments", () => {
      const result = mockDeepLink._invoke(
        "issue",
        new URLSearchParams("url=https://github.com/org/repo/issues/42/edit"),
      );
      expect(result).toBe(false);
    });

    it("rejects issue URLs with zero or negative issue number", () => {
      expect(
        mockDeepLink._invoke(
          "issue",
          new URLSearchParams("url=https://github.com/org/repo/issues/0"),
        ),
      ).toBe(false);

      expect(
        mockDeepLink._invoke(
          "issue",
          new URLSearchParams("url=https://github.com/org/repo/issues/-1"),
        ),
      ).toBe(false);
    });

    it("accepts valid GitHub issue URL", () => {
      const listener = vi.fn();
      service.on(NewTaskLinkEvent.Action, listener);

      const result = mockDeepLink._invoke(
        "issue",
        new URLSearchParams("url=https://github.com/posthog/posthog/issues/42"),
      );

      expect(result).toBe(true);
      expect(listener).toHaveBeenCalledWith(
        expect.objectContaining({
          action: "issue",
          url: "https://github.com/posthog/posthog/issues/42",
          owner: "posthog",
          issueRepo: "posthog",
          issueNumber: 42,
        }),
      );
    });

    it("passes shared params", () => {
      const listener = vi.fn();
      service.on(NewTaskLinkEvent.Action, listener);

      mockDeepLink._invoke(
        "issue",
        new URLSearchParams(
          "url=https://github.com/org/repo/issues/1&repo=other/repo&model=opus",
        ),
      );

      expect(listener).toHaveBeenCalledWith(
        expect.objectContaining({
          repo: "other/repo",
          model: "opus",
        }),
      );
    });
  });

  describe("emitOrQueue", () => {
    it("emits when listeners exist", () => {
      const listener = vi.fn();
      service.on(NewTaskLinkEvent.Action, listener);

      mockDeepLink._invoke("new", new URLSearchParams("prompt=test"));

      expect(listener).toHaveBeenCalledTimes(1);
      expect(service.consumePendingLink()).toBeNull();
    });

    it("queues when no listeners exist", () => {
      mockDeepLink._invoke("new", new URLSearchParams("prompt=test"));

      const pending = service.consumePendingLink();
      expect(pending).toEqual(
        expect.objectContaining({ action: "new", prompt: "test" }),
      );
    });

    it("focuses the window", () => {
      mockDeepLink._invoke("new", new URLSearchParams("prompt=test"));

      expect(mockWindow.focus).toHaveBeenCalled();
    });

    it("restores the window if minimized", () => {
      vi.mocked(mockWindow.isMinimized).mockReturnValue(true);

      mockDeepLink._invoke("new", new URLSearchParams("prompt=test"));

      expect(mockWindow.restore).toHaveBeenCalled();
      expect(mockWindow.focus).toHaveBeenCalled();
    });

    it("does not restore the window if not minimized", () => {
      vi.mocked(mockWindow.isMinimized).mockReturnValue(false);

      mockDeepLink._invoke("new", new URLSearchParams("prompt=test"));

      expect(mockWindow.restore).not.toHaveBeenCalled();
    });
  });

  describe("consumePendingLink", () => {
    it("returns null when no pending link", () => {
      expect(service.consumePendingLink()).toBeNull();
    });

    it("clears after consuming", () => {
      mockDeepLink._invoke("new", new URLSearchParams("prompt=test"));

      expect(service.consumePendingLink()).not.toBeNull();
      expect(service.consumePendingLink()).toBeNull();
    });

    it("latest link overwrites previous pending", () => {
      mockDeepLink._invoke("new", new URLSearchParams("prompt=first"));
      mockDeepLink._invoke("new", new URLSearchParams("prompt=second"));

      const pending = service.consumePendingLink();
      expect(pending).toEqual(expect.objectContaining({ prompt: "second" }));
    });
  });
});
