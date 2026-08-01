import type { IDeepLinkRegistry } from "@posthog/platform/deep-link";
import type { IMainWindow } from "@posthog/platform/main-window";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TaskLinkEvent, TaskLinkService } from "./task-link";

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
    _invoke(key: string, path: string) {
      const handler = handlers.get(key);
      if (!handler) throw new Error(`No handler for key: ${key}`);
      return handler(path, new URLSearchParams());
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

describe("TaskLinkService", () => {
  let service: TaskLinkService;
  let mockDeepLink: ReturnType<typeof createMockDeepLinkService>;
  let mockWindow: IMainWindow;

  beforeEach(() => {
    vi.clearAllMocks();
    mockDeepLink = createMockDeepLinkService();
    mockWindow = createMockMainWindow();
    service = new TaskLinkService(
      mockDeepLink as unknown as IDeepLinkRegistry,
      mockWindow,
      makeLogger(),
    );
  });

  describe("constructor", () => {
    it("registers a handler for the task key", () => {
      expect(mockDeepLink.registerHandler).toHaveBeenCalledWith(
        "task",
        expect.any(Function),
      );
    });
  });

  describe("handleTaskLink", () => {
    it("rejects an empty path with no task ID", () => {
      expect(mockDeepLink._invoke("task", "")).toBe(false);
    });

    it("emits OpenTask with just a task ID when a listener exists", () => {
      const listener = vi.fn();
      service.on(TaskLinkEvent.OpenTask, listener);

      const result = mockDeepLink._invoke("task", "task-123");

      expect(result).toBe(true);
      expect(listener).toHaveBeenCalledWith({
        taskId: "task-123",
        taskRunId: undefined,
      });
    });

    it("parses a task run ID from the .../run/<id> path", () => {
      const listener = vi.fn();
      service.on(TaskLinkEvent.OpenTask, listener);

      mockDeepLink._invoke("task", "task-123/run/run-456");

      expect(listener).toHaveBeenCalledWith({
        taskId: "task-123",
        taskRunId: "run-456",
      });
    });

    it("ignores a second path segment that is not 'run'", () => {
      const listener = vi.fn();
      service.on(TaskLinkEvent.OpenTask, listener);

      mockDeepLink._invoke("task", "task-123/foo/bar");

      expect(listener).toHaveBeenCalledWith({
        taskId: "task-123",
        taskRunId: undefined,
      });
    });

    it("focuses the window and restores it when minimized", () => {
      vi.mocked(mockWindow.isMinimized).mockReturnValue(true);

      mockDeepLink._invoke("task", "task-123");

      expect(mockWindow.restore).toHaveBeenCalled();
      expect(mockWindow.focus).toHaveBeenCalled();
    });

    it("does not restore the window when it is not minimized", () => {
      vi.mocked(mockWindow.isMinimized).mockReturnValue(false);

      mockDeepLink._invoke("task", "task-123");

      expect(mockWindow.restore).not.toHaveBeenCalled();
      expect(mockWindow.focus).toHaveBeenCalled();
    });
  });

  describe("pending deep link queueing", () => {
    it("queues the link when no listeners exist", () => {
      mockDeepLink._invoke("task", "task-123/run/run-456");

      expect(service.consumePendingDeepLink()).toEqual({
        taskId: "task-123",
        taskRunId: "run-456",
      });
    });

    it("clears the pending link after consuming it", () => {
      mockDeepLink._invoke("task", "task-123");

      expect(service.consumePendingDeepLink()).not.toBeNull();
      expect(service.consumePendingDeepLink()).toBeNull();
    });

    it("does not queue when a listener is present", () => {
      service.on(TaskLinkEvent.OpenTask, vi.fn());

      mockDeepLink._invoke("task", "task-123");

      expect(service.consumePendingDeepLink()).toBeNull();
    });

    it("returns null when nothing is pending", () => {
      expect(service.consumePendingDeepLink()).toBeNull();
    });
  });
});
