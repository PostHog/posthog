import { HttpResponse, http } from "msw";

type AnyHttpResponse = Response | ReturnType<typeof HttpResponse.json>;

export interface PostHogHandlersOptions {
  baseUrl?: string;
  onAppendLog?: (entries: unknown[]) => void;
  onUpdateTaskRun?: (body: unknown) => void;
  getTask?: () => unknown;
  getTaskRun?: () => unknown;
  appendLogResponse?: () => AnyHttpResponse;
}

export function createPostHogHandlers(options: PostHogHandlersOptions = {}) {
  const {
    baseUrl = "http://localhost:8000",
    onAppendLog,
    onUpdateTaskRun,
    getTask,
    getTaskRun,
    appendLogResponse,
  } = options;

  return [
    // GET local LLM gateway models - session initialization fetches these in the
    // background for command/model metadata.
    http.get("http://localhost:3308/:product/v1/models", () => {
      return HttpResponse.json({
        object: "list",
        data: [
          {
            id: "claude-opus-4-8",
            owned_by: "anthropic",
            context_window: 200000,
            supports_streaming: true,
            supports_vision: true,
          },
          {
            id: "gpt-5.5",
            owned_by: "openai",
            context_window: 200000,
            supports_streaming: true,
            supports_vision: true,
          },
        ],
      });
    }),

    // POST /append_log/ - Agent log entries
    http.post(
      `${baseUrl}/api/projects/:projectId/tasks/:taskId/runs/:runId/append_log/`,
      async ({ request }) => {
        if (appendLogResponse) {
          return appendLogResponse();
        }
        const body = (await request.json()) as { entries: unknown[] };
        if (body.entries?.length > 0) {
          onAppendLog?.(body.entries);
        }
        return HttpResponse.json({});
      },
    ),

    // GET /tasks/:taskId - Fetch task details
    http.get(`${baseUrl}/api/projects/:projectId/tasks/:taskId/`, () => {
      const task = getTask?.() ?? {
        id: "test-task-id",
        title: "Test task",
        description: null,
        origin_product: "user_created",
        repository: "test/repo",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
      return HttpResponse.json(task);
    }),

    // GET /runs/:runId - Fetch task run details
    http.get(
      `${baseUrl}/api/projects/:projectId/tasks/:taskId/runs/:runId/`,
      () => {
        const taskRun = getTaskRun?.() ?? { log_url: "" };
        return HttpResponse.json(taskRun);
      },
    ),

    // PATCH /runs/:runId - Update task run
    http.patch(
      `${baseUrl}/api/projects/:projectId/tasks/:taskId/runs/:runId/`,
      async ({ request }) => {
        onUpdateTaskRun?.(await request.json());
        return HttpResponse.json({});
      },
    ),
  ];
}
