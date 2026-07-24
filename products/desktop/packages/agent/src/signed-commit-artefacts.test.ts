import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  reportCommitArtefacts,
  reportTaskRunBranch,
} from "./signed-commit-artefacts";

const ENV = {
  POSTHOG_API_URL: "https://us.posthog.com",
  POSTHOG_PERSONAL_API_KEY: "pha_test",
  POSTHOG_PROJECT_ID: "7",
};

// Point the env-file read at a path that never exists so only `env` is used.
const NO_ENV_FILE = "/nonexistent/agent-env";

const RESULT = {
  branch: "posthog-code/fix-foo",
  repository: "posthog/posthog",
  commits: [
    { sha: "aaa111", url: "https://github.com/posthog/posthog/commit/aaa111" },
    { sha: "bbb222", url: "https://github.com/posthog/posthog/commit/bbb222" },
  ],
};

describe("reportCommitArtefacts", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(process.stderr, "write").mockImplementation(() => true);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  function jsonResponse(body: unknown): Response {
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }

  it("posts one commit artefact per commit per associated report, attributed via header", async () => {
    fetchMock.mockImplementation(async (url: string | URL) => {
      if (String(url).includes("/signals/reports/?")) {
        return jsonResponse({
          results: [{ id: "report-1" }, { id: "report-2" }],
        });
      }
      return jsonResponse({ id: "artefact" });
    });

    await reportCommitArtefacts({
      taskId: "task-1",
      result: RESULT,
      message: "fix: foo",
      env: ENV,
      envFilePath: NO_ENV_FILE,
    });

    const lookupCalls = fetchMock.mock.calls.filter(([url]) =>
      String(url).includes("/signals/reports/?task_id=task-1"),
    );
    expect(lookupCalls).toHaveLength(1);

    const postCalls = fetchMock.mock.calls.filter(([url]) =>
      String(url).includes("/artefacts/"),
    );
    // 2 commits × 2 reports.
    expect(postCalls).toHaveLength(4);
    for (const [url, init] of postCalls) {
      expect(String(url)).toMatch(
        /\/api\/projects\/7\/signals\/reports\/report-[12]\/artefacts\/$/,
      );
      const headers = new Headers((init as RequestInit).headers);
      expect(headers.get("X-PostHog-Task-Id")).toBe("task-1");
      const body = JSON.parse(String((init as RequestInit).body));
      expect(body.artefact_type).toBe("commit");
      expect(body.content.repository).toBe("posthog/posthog");
      expect(body.content.branch).toBe("posthog-code/fix-foo");
      expect(["aaa111", "bbb222"]).toContain(body.content.commit_sha);
      expect(body.content.message).toBe("fix: foo");
    }
  });

  it("is a no-op without a task id", async () => {
    await reportCommitArtefacts({
      taskId: undefined,
      result: RESULT,
      message: "fix: foo",
      env: ENV,
      envFilePath: NO_ENV_FILE,
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("is a no-op without sandbox PostHog credentials", async () => {
    await reportCommitArtefacts({
      taskId: "task-1",
      result: RESULT,
      message: "fix: foo",
      env: {},
      envFilePath: NO_ENV_FILE,
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("never throws when the report lookup fails", async () => {
    fetchMock.mockRejectedValue(new Error("network down"));
    await expect(
      reportCommitArtefacts({
        taskId: "task-1",
        result: RESULT,
        message: "fix: foo",
        env: ENV,
        envFilePath: NO_ENV_FILE,
      }),
    ).resolves.toBeUndefined();
  });

  it("keeps posting remaining artefacts when one post fails", async () => {
    let postCount = 0;
    fetchMock.mockImplementation(async (url: string | URL) => {
      if (String(url).includes("/signals/reports/?")) {
        return jsonResponse({ results: [{ id: "report-1" }] });
      }
      postCount += 1;
      if (postCount === 1) {
        return new Response("{}", { status: 500 });
      }
      return jsonResponse({ id: "artefact" });
    });

    await reportCommitArtefacts({
      taskId: "task-1",
      result: RESULT,
      message: "fix: foo",
      env: ENV,
      envFilePath: NO_ENV_FILE,
    });

    // Both commits attempted despite the first failing.
    expect(postCount).toBe(2);
  });
});

describe("reportTaskRunBranch", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(process.stderr, "write").mockImplementation(() => true);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("persists the signed commit branch on the task run", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({}), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await reportTaskRunBranch({
      taskId: "task-1",
      taskRunId: "run-1",
      branch: "posthog-code/fix-foo",
      env: ENV,
      envFilePath: NO_ENV_FILE,
    });

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe(
      "https://us.posthog.com/api/projects/7/tasks/task-1/runs/run-1/",
    );
    expect(init).toMatchObject({
      method: "PATCH",
      body: JSON.stringify({
        branch: "posthog-code/fix-foo",
        output: { head_branch: "posthog-code/fix-foo" },
      }),
    });
  });
});
