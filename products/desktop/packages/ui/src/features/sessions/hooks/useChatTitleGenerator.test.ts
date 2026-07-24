import type { Task } from "@posthog/shared/domain-types";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockEnrichDescription = vi.hoisted(() =>
  vi.fn().mockImplementation((desc: string) => Promise.resolve(desc)),
);
const mockGenerateTitle = vi.hoisted(() => vi.fn());
const mockGetQueriesData = vi.hoisted(() => vi.fn(() => [] as unknown[]));
const mockIsAuthenticated = vi.hoisted(() => ({ value: true }));
const mockUpdateTask = vi.hoisted(() => vi.fn().mockResolvedValue(undefined));
const mockSetQueriesData = vi.hoisted(() => vi.fn());
const mockSetQueryData = vi.hoisted(() => vi.fn());
const mockUpdateSessionTaskTitle = vi.hoisted(() => vi.fn());
const mockPrompts = vi.hoisted(() => ({ value: [] as string[] }));
const mockSessionSummary = vi.hoisted(() => ({
  value: undefined as string | undefined,
}));
const mockSessionStoreSetters = vi.hoisted(() => ({ updateSession: vi.fn() }));
const mockTitleAttachmentPaths = vi.hoisted(() => ({ value: [] as string[] }));
const mockTitleAttachmentClear = vi.hoisted(() => vi.fn());

vi.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({
    getQueriesData: mockGetQueriesData,
    setQueriesData: mockSetQueriesData,
    setQueryData: mockSetQueryData,
  }),
}));

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => ({ updateTask: mockUpdateTask }),
}));

vi.mock("@posthog/ui/features/auth/store", () => ({
  useAuthStateValue: (
    selector: (state: {
      status: string;
      cloudRegion: string | null;
    }) => unknown,
  ) =>
    selector(
      mockIsAuthenticated.value
        ? { status: "authenticated", cloudRegion: "us-east-1" }
        : { status: "anonymous", cloudRegion: null },
    ),
}));

vi.mock("@posthog/core/sessions/sessionEvents", () => ({
  extractUserPromptsFromEvents: () => mockPrompts.value,
}));

vi.mock("@posthog/di/react", () => ({
  useService: () => ({
    updateSessionTaskTitle: mockUpdateSessionTaskTitle,
    enrichDescriptionWithFileContent: mockEnrichDescription,
    generateTitleAndSummary: mockGenerateTitle,
  }),
}));

vi.mock("@posthog/ui/shell/logger", () => ({
  logger: {
    scope: () => ({
      info: vi.fn(),
      debug: vi.fn(),
      warn: vi.fn(),
      error: vi.fn(),
    }),
  },
}));

vi.mock("@posthog/ui/shell/titleAttachmentStore", () => ({
  titleAttachmentStoreApi: {
    get: () => mockTitleAttachmentPaths.value,
    set: vi.fn(),
    clear: mockTitleAttachmentClear,
  },
}));

vi.mock("@posthog/ui/features/sessions/sessionStore", () => {
  const state = {
    taskIdIndex: { "task-1": "run-1" },
    get sessions() {
      return {
        "run-1": {
          events: mockPrompts.value,
          conversationSummary: mockSessionSummary.value,
        },
      };
    },
  };
  const fn = Object.assign(
    (selector: (s: typeof state) => unknown) => selector(state),
    { getState: () => state },
  );
  return {
    useSessionStore: fn,
    sessionStoreSetters: mockSessionStoreSetters,
  };
});

import { useTitleGenerationStore } from "@posthog/ui/features/sessions/titleGenerationStore";
import { useChatTitleGenerator } from "./useChatTitleGenerator";

const TASK_ID = "task-1";

function createTask(overrides: Partial<Task> = {}): Task {
  return {
    id: TASK_ID,
    task_number: 1,
    slug: "task-1",
    title: "Fix the login bug",
    description: "Fix the login bug",
    created_at: "2026-05-28T00:00:00.000Z",
    updated_at: "2026-05-28T00:00:00.000Z",
    origin_product: "user_created",
    ...overrides,
  } as Task;
}

// Simulate a task present in the ["tasks","list"] cache so the inlined
// getCachedTask (which reads queryClient.getQueriesData) finds it.
function cacheTask(task: Task): void {
  mockGetQueriesData.mockReturnValue([[["tasks", "list"], [task]]]);
}

interface TitleAndSummaryResult {
  title: string;
  summary: string;
}

describe("useChatTitleGenerator", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useTitleGenerationStore.setState({ byTaskId: {} });
    mockIsAuthenticated.value = true;
    mockPrompts.value = [];
    mockSessionSummary.value = undefined;
    mockTitleAttachmentPaths.value = [];
    mockEnrichDescription.mockImplementation((desc: string) =>
      Promise.resolve(desc),
    );
    mockGetQueriesData.mockReturnValue([]);
  });

  it("does not generate when promptCount is 0 and the task already has a custom title", () => {
    renderHook(() =>
      useChatTitleGenerator(createTask({ title: "Custom task title" })),
    );
    expect(mockGenerateTitle).not.toHaveBeenCalled();
  });

  it("generates title from the saved task description before prompt events arrive", async () => {
    mockGenerateTitle.mockResolvedValue({
      title: "Fix login bug",
      summary: "User is fixing a login issue",
    });

    renderHook(() => useChatTitleGenerator(createTask()));

    await waitFor(() => {
      expect(mockEnrichDescription).toHaveBeenCalledWith(
        "Fix the login bug",
        [],
      );
    });
    await waitFor(() => {
      expect(mockUpdateTask).toHaveBeenCalledWith(TASK_ID, {
        title: "Fix login bug",
      });
    });
  });

  it("generates title when the task has no title yet", async () => {
    mockGenerateTitle.mockResolvedValue({
      title: "Fix login bug",
      summary: "User is fixing a login issue",
    });

    renderHook(() => useChatTitleGenerator(createTask({ title: "" })));

    await waitFor(() => {
      expect(mockUpdateTask).toHaveBeenCalledWith(TASK_ID, {
        title: "Fix login bug",
      });
    });
  });

  it("regenerates title when title_manually_set is true but the title still matches the fallback", async () => {
    mockGenerateTitle.mockResolvedValue({
      title: "Fix login bug",
      summary: "User is fixing a login issue",
    });
    cacheTask(createTask({ title_manually_set: true }));

    renderHook(() =>
      useChatTitleGenerator(createTask({ title_manually_set: true })),
    );

    await waitFor(() => {
      expect(mockUpdateTask).toHaveBeenCalledWith(TASK_ID, {
        title: "Fix login bug",
      });
    });
  });

  it("generates title on first prompt", async () => {
    mockGenerateTitle.mockResolvedValue({
      title: "Fix login bug",
      summary: "User is fixing a login issue",
    });
    mockPrompts.value = ["Fix the login bug"];

    renderHook(() =>
      useChatTitleGenerator(createTask({ title: "Raw prompt title" })),
    );

    await waitFor(() => {
      expect(mockUpdateTask).toHaveBeenCalledWith(TASK_ID, {
        title: "Fix login bug",
      });
    });
    expect(mockSetQueriesData).toHaveBeenCalledWith(
      { queryKey: ["tasks", "list"] },
      expect.any(Function),
    );
    expect(mockSetQueriesData).toHaveBeenCalledWith(
      { queryKey: ["tasks", "summaries"] },
      expect.any(Function),
    );
  });

  it.each([
    { name: "no summary", summary: "", expectsSummaryUpdate: false },
    {
      name: "with summary",
      summary: "User wants to fix auth",
      expectsSummaryUpdate: true,
    },
  ])(
    "skips title update when title_manually_set ($name)",
    async ({ summary, expectsSummaryUpdate }) => {
      cacheTask(
        createTask({
          title: "Custom auth title",
          description: "fix auth",
          title_manually_set: true,
        }),
      );
      mockGenerateTitle.mockResolvedValue({ title: "Auto title", summary });
      mockPrompts.value = ["fix auth"];

      renderHook(() =>
        useChatTitleGenerator(
          createTask({
            title: "Custom auth title",
            description: "fix auth",
            title_manually_set: true,
          }),
        ),
      );

      await waitFor(() => {
        expect(mockGenerateTitle).toHaveBeenCalled();
      });
      expect(mockUpdateTask).not.toHaveBeenCalled();

      if (expectsSummaryUpdate) {
        await waitFor(() => {
          expect(mockSessionStoreSetters.updateSession).toHaveBeenCalledWith(
            "run-1",
            { conversationSummary: summary },
          );
        });
      } else {
        expect(mockSessionStoreSetters.updateSession).not.toHaveBeenCalled();
      }
    },
  );

  it("calls enrichDescriptionWithFileContent before generating", async () => {
    mockEnrichDescription.mockResolvedValue("enriched content");
    mockGenerateTitle.mockResolvedValue({
      title: "Enriched title",
      summary: "",
    });
    mockPrompts.value = ['<file path="/tmp/code.ts" />'];

    renderHook(() =>
      useChatTitleGenerator(
        createTask({
          title: "Code file prompt",
          description: "Code file prompt",
        }),
      ),
    );

    await waitFor(() => {
      expect(mockEnrichDescription).toHaveBeenCalledWith(
        '1. <file path="/tmp/code.ts" />',
        [],
      );
      expect(mockGenerateTitle).toHaveBeenCalledWith("enriched content");
    });
  });

  it("passes stashed local attachment paths and clears them after naming", async () => {
    mockTitleAttachmentPaths.value = ["/tmp/clip/pasted-text.txt"];
    mockEnrichDescription.mockResolvedValue("Refactor the auth flow");
    mockGenerateTitle.mockResolvedValue({
      title: "Refactor auth flow",
      summary: "",
    });
    mockPrompts.value = ["[Attached files: pasted-text.txt]"];

    renderHook(() =>
      useChatTitleGenerator(
        createTask({
          title: "",
          description: "Attached files: pasted-text.txt",
        }),
      ),
    );

    await waitFor(() => {
      expect(mockEnrichDescription).toHaveBeenCalledWith(
        "1. [Attached files: pasted-text.txt]",
        ["/tmp/clip/pasted-text.txt"],
      );
    });
    await waitFor(() => {
      expect(mockUpdateTask).toHaveBeenCalledWith(TASK_ID, {
        title: "Refactor auth flow",
      });
    });
    expect(mockTitleAttachmentClear).toHaveBeenCalledWith(TASK_ID);
  });

  it("does not clear stashed paths when generation returns null (keeps them for prompt-path retry)", async () => {
    mockTitleAttachmentPaths.value = ["/tmp/clip/pasted-text.txt"];
    mockGenerateTitle.mockResolvedValue(null);
    mockPrompts.value = ["[Attached files: pasted-text.txt]"];

    renderHook(() =>
      useChatTitleGenerator(
        createTask({
          title: "",
          description: "Attached files: pasted-text.txt",
        }),
      ),
    );

    await waitFor(() => {
      expect(mockGenerateTitle).toHaveBeenCalled();
    });
    expect(mockTitleAttachmentClear).not.toHaveBeenCalled();
  });

  it("updates conversation summary when returned", async () => {
    mockGenerateTitle.mockResolvedValue({
      title: "Some title",
      summary: "User wants to fix auth",
    });
    mockPrompts.value = ["fix auth"];

    renderHook(() =>
      useChatTitleGenerator(
        createTask({ title: "Auth prompt", description: "fix auth" }),
      ),
    );

    await waitFor(() => {
      expect(mockSessionStoreSetters.updateSession).toHaveBeenCalledWith(
        "run-1",
        { conversationSummary: "User wants to fix auth" },
      );
    });
  });

  it("does not update when generateTitleAndSummary returns null", async () => {
    mockGenerateTitle.mockResolvedValue(null);
    mockPrompts.value = ["some prompt"];

    renderHook(() =>
      useChatTitleGenerator(
        createTask({ title: "Some prompt", description: "some prompt" }),
      ),
    );

    await waitFor(() => {
      expect(mockGenerateTitle).toHaveBeenCalled();
    });
    expect(mockUpdateTask).not.toHaveBeenCalled();
  });

  it("waits for authentication before generating", () => {
    mockIsAuthenticated.value = false;

    renderHook(() => useChatTitleGenerator(createTask()));

    expect(mockGenerateTitle).not.toHaveBeenCalled();
  });

  it("does not regenerate when the chat view remounts after a generation", async () => {
    mockGenerateTitle.mockResolvedValue({
      title: "Fix login bug",
      summary: "User is fixing a login issue",
    });
    mockPrompts.value = ["Fix the login bug"];

    const first = renderHook(() =>
      useChatTitleGenerator(createTask({ title: "Raw prompt title" })),
    );
    await waitFor(() => {
      expect(mockGenerateTitle).toHaveBeenCalledTimes(1);
    });
    first.unmount();

    renderHook(() =>
      useChatTitleGenerator(createTask({ title: "Fix login bug" })),
    );

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(mockGenerateTitle).toHaveBeenCalledTimes(1);
  });

  it("shares one in-flight guard across simultaneously mounted views", async () => {
    let resolveGeneration!: (value: TitleAndSummaryResult) => void;
    mockGenerateTitle.mockReturnValue(
      new Promise((resolve) => {
        resolveGeneration = resolve;
      }),
    );
    mockPrompts.value = ["Fix the login bug"];

    renderHook(() =>
      useChatTitleGenerator(createTask({ title: "Raw prompt title" })),
    );
    renderHook(() =>
      useChatTitleGenerator(createTask({ title: "Raw prompt title" })),
    );

    await waitFor(() => {
      expect(mockGenerateTitle).toHaveBeenCalledTimes(1);
    });

    resolveGeneration({ title: "Fix login bug", summary: "" });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(mockGenerateTitle).toHaveBeenCalledTimes(1);
  });

  it("does not rewrite an unlocked real title from later prompts, but still refreshes the summary", async () => {
    // Auto-generated at creation: real title, title_manually_set false.
    const unlockedTask = createTask({
      title: "Fix login bug",
      description: "the login page 500s for SSO users",
    });
    cacheTask(unlockedTask);
    mockGenerateTitle.mockResolvedValue({
      title: "Discuss deploy schedule",
      summary: "User is coordinating a deploy",
    });
    mockPrompts.value = Array.from({ length: 8 }, (_, i) => `prompt ${i}`);

    renderHook(() => useChatTitleGenerator(unlockedTask));

    await waitFor(() => {
      expect(mockGenerateTitle).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      expect(mockSessionStoreSetters.updateSession).toHaveBeenCalledWith(
        "run-1",
        { conversationSummary: "User is coordinating a deploy" },
      );
    });
    expect(mockUpdateTask).not.toHaveBeenCalled();
  });

  it("replaces a placeholder title from later prompts", async () => {
    const placeholderTask = createTask({
      title: "Attached files: pasted-text.txt",
      description: "Attached files: pasted-text.txt",
    });
    cacheTask(placeholderTask);
    mockGenerateTitle.mockResolvedValue({
      title: "Refactor auth flow",
      summary: "",
    });
    mockPrompts.value = Array.from({ length: 8 }, (_, i) => `prompt ${i}`);

    renderHook(() => useChatTitleGenerator(placeholderTask));

    await waitFor(() => {
      expect(mockUpdateTask).toHaveBeenCalledWith(TASK_ID, {
        title: "Refactor auth flow",
      });
    });
  });

  it("skips catch-up generation when the title is locked and a summary exists", async () => {
    const lockedTask = createTask({
      title: "Custom auth title",
      description: "fix auth",
      title_manually_set: true,
    });
    cacheTask(lockedTask);
    mockSessionSummary.value = "User wants to fix auth";
    mockPrompts.value = Array.from({ length: 8 }, (_, i) => `prompt ${i}`);

    renderHook(() => useChatTitleGenerator(lockedTask));

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(mockGenerateTitle).not.toHaveBeenCalled();
  });

  it("runs catch-up generation for a locked title when no summary exists yet", async () => {
    const lockedTask = createTask({
      title: "Custom auth title",
      description: "fix auth",
      title_manually_set: true,
    });
    cacheTask(lockedTask);
    mockGenerateTitle.mockResolvedValue({
      title: "Auto title",
      summary: "User wants to fix auth",
    });
    mockPrompts.value = Array.from({ length: 8 }, (_, i) => `prompt ${i}`);

    renderHook(() => useChatTitleGenerator(lockedTask));

    await waitFor(() => {
      expect(mockGenerateTitle).toHaveBeenCalledTimes(1);
    });
    expect(mockUpdateTask).not.toHaveBeenCalled();
  });
});
