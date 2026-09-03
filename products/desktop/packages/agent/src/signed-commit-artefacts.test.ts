import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import {
  parseSandboxEnv,
  reportCommitArtefacts,
  reportTaskRunBranch,
  reportTaskRunCommits,
  resolveSandboxPosthogApi,
} from "./signed-commit-artefacts";

describe("parseSandboxEnv", () => {
  it("parses NUL-delimited entries into an object", () => {
    expect(parseSandboxEnv("FIRST=one\0SECOND=two\0")).toEqual({
      FIRST: "one",
      SECOND: "two",
    });
  });

  it("preserves equals signs in values and ignores malformed entries", () => {
    expect(
      parseSandboxEnv("TOKEN=header.payload=signature\0invalid\0=value\0"),
    ).toEqual({ TOKEN: "header.payload=signature" });
  });
});

const ENV = {
  POSTHOG_API_URL: "https://us.posthog.com",
  POSTHOG_PERSONAL_API_KEY: "pha_test",
  POSTHOG_PROJECT_ID: "7",
};

// Point the env-file read at a path that never exists so only `env` is used.
const NO_ENV_FILE = "/nonexistent/agent-env";
const TEST_OAUTH_ENV_FILE = path.join(
  tmpdir(),
  `posthog-agent-oauth-env-${process.pid}`,
);

beforeAll(async () => {
  await writeFile(TEST_OAUTH_ENV_FILE, "POSTHOG_PERSONAL_API_KEY=pha_test\0");
});

afterAll(async () => {
  await rm(TEST_OAUTH_ENV_FILE, { force: true });
});

describe("resolveSandboxPosthogApi", () => {
  it("reads the rotating API key from the dedicated OAuth file", async () => {
    const directory = await mkdtemp(
      path.join(tmpdir(), "sandbox-posthog-api-"),
    );
    const envFilePath = path.join(directory, "agent-env");
    const oauthEnvFilePath = path.join(directory, "agent-oauth-env");

    try {
      await writeFile(
        envFilePath,
        "POSTHOG_API_URL=https://us.posthog.com\0POSTHOG_PROJECT_ID=7\0",
      );
      await writeFile(
        oauthEnvFilePath,
        "POSTHOG_PERSONAL_API_KEY=pha_refreshed\0",
      );

      expect(
        resolveSandboxPosthogApi({}, envFilePath, oauthEnvFilePath),
      ).toEqual({
        apiUrl: "https://us.posthog.com",
        apiKey: "pha_refreshed",
        projectId: 7,
      });
    } finally {
      await rm(directory, { recursive: true, force: true });
    }
  });

  it("fails closed without the dedicated OAuth file", () => {
    expect(
      resolveSandboxPosthogApi(ENV, NO_ENV_FILE, NO_ENV_FILE),
    ).toBeUndefined();
  });

  it("does not resurrect a stale token when the OAuth file is empty", async () => {
    const directory = await mkdtemp(
      path.join(tmpdir(), "sandbox-posthog-api-"),
    );
    const envFilePath = path.join(directory, "agent-env");
    const oauthEnvFilePath = path.join(directory, "agent-oauth-env");

    try {
      await writeFile(
        envFilePath,
        "POSTHOG_API_URL=https://us.posthog.com\0POSTHOG_PERSONAL_API_KEY=pha_stale\0POSTHOG_PROJECT_ID=7\0",
      );
      await writeFile(oauthEnvFilePath, "");

      expect(
        resolveSandboxPosthogApi(ENV, envFilePath, oauthEnvFilePath),
      ).toBeUndefined();
    } finally {
      await rm(directory, { recursive: true, force: true });
    }
  });

  it("fails closed when the managed OAuth file is unreadable", async () => {
    const directory = await mkdtemp(
      path.join(tmpdir(), "sandbox-posthog-api-"),
    );
    const envFilePath = path.join(directory, "agent-env");

    try {
      await writeFile(
        envFilePath,
        "POSTHOG_API_URL=https://us.posthog.com\0POSTHOG_PROJECT_ID=7\0",
      );

      expect(
        resolveSandboxPosthogApi(ENV, envFilePath, directory),
      ).toBeUndefined();
    } finally {
      await rm(directory, { recursive: true, force: true });
    }
  });
});

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
      oauthEnvFilePath: TEST_OAUTH_ENV_FILE,
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

  it("rereads the OAuth file when credentials rotate between requests", async () => {
    const directory = await mkdtemp(
      path.join(tmpdir(), "sandbox-posthog-api-"),
    );
    const oauthEnvFilePath = path.join(directory, "agent-oauth-env");
    await writeFile(oauthEnvFilePath, "POSTHOG_PERSONAL_API_KEY=pha_initial\0");

    try {
      fetchMock.mockImplementationOnce(async () => {
        await writeFile(
          oauthEnvFilePath,
          "POSTHOG_PERSONAL_API_KEY=pha_rotated\0",
        );
        return jsonResponse({ results: [{ id: "report-1" }] });
      });
      fetchMock.mockImplementation(async () =>
        jsonResponse({ id: "artefact" }),
      );

      await reportCommitArtefacts({
        taskId: "task-1",
        result: { ...RESULT, commits: [RESULT.commits[0]] },
        message: "fix: foo",
        env: ENV,
        envFilePath: NO_ENV_FILE,
        oauthEnvFilePath,
      });

      expect(fetchMock).toHaveBeenCalledTimes(2);
      expect(
        (fetchMock.mock.calls[0]?.[1]?.headers as Headers).get("Authorization"),
      ).toBe("Bearer pha_initial");
      expect(
        (fetchMock.mock.calls[1]?.[1]?.headers as Headers).get("Authorization"),
      ).toBe("Bearer pha_rotated");
    } finally {
      await rm(directory, { recursive: true, force: true });
    }
  });

  it("rereads the OAuth file when retrying an auth failure", async () => {
    const directory = await mkdtemp(
      path.join(tmpdir(), "sandbox-posthog-api-"),
    );
    const oauthEnvFilePath = path.join(directory, "agent-oauth-env");
    await writeFile(oauthEnvFilePath, "POSTHOG_PERSONAL_API_KEY=pha_initial\0");

    try {
      fetchMock.mockImplementationOnce(async () => {
        await writeFile(
          oauthEnvFilePath,
          "POSTHOG_PERSONAL_API_KEY=pha_rotated\0",
        );
        return new Response(null, { status: 401 });
      });
      fetchMock.mockImplementationOnce(async () =>
        jsonResponse({ results: [] }),
      );

      await reportCommitArtefacts({
        taskId: "task-1",
        result: RESULT,
        message: "fix: foo",
        env: ENV,
        envFilePath: NO_ENV_FILE,
        oauthEnvFilePath,
      });

      expect(fetchMock).toHaveBeenCalledTimes(2);
      expect(
        (fetchMock.mock.calls[1]?.[1]?.headers as Headers).get("Authorization"),
      ).toBe("Bearer pha_rotated");
    } finally {
      await rm(directory, { recursive: true, force: true });
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
        oauthEnvFilePath: TEST_OAUTH_ENV_FILE,
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
      oauthEnvFilePath: TEST_OAUTH_ENV_FILE,
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
      repository: "PostHog/PostHog",
      branch: "posthog-code/fix-foo",
      env: ENV,
      envFilePath: NO_ENV_FILE,
      oauthEnvFilePath: TEST_OAUTH_ENV_FILE,
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
        output: {
          head_branch: "posthog-code/fix-foo",
          head_branches: [
            {
              repository: "posthog/posthog",
              branch: "posthog-code/fix-foo",
            },
          ],
        },
      }),
    });
  });

  it("can report a PR head branch without changing the checkout branch", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({}), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await reportTaskRunBranch({
      taskId: "task-1",
      taskRunId: "run-1",
      repository: "PostHog/PostHog",
      branch: "posthog-code/fix-foo",
      updateCheckoutBranch: false,
      env: ENV,
      envFilePath: NO_ENV_FILE,
      oauthEnvFilePath: TEST_OAUTH_ENV_FILE,
    });

    const [, init] = fetchMock.mock.calls[0];
    expect(init).toMatchObject({
      method: "PATCH",
      body: JSON.stringify({
        output: {
          head_branch: "posthog-code/fix-foo",
          head_branches: [
            {
              repository: "posthog/posthog",
              branch: "posthog-code/fix-foo",
            },
          ],
        },
      }),
    });
  });
});

describe("reportTaskRunCommits", () => {
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

  it("stores the successful push on the task run", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({}), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await reportTaskRunCommits({
      taskId: "task-1",
      taskRunId: "run-1",
      result: RESULT,
      message: "feat(desktop): show commits",
      env: ENV,
      envFilePath: NO_ENV_FILE,
      oauthEnvFilePath: TEST_OAUTH_ENV_FILE,
    });

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe(
      "https://us.posthog.com/api/projects/7/tasks/task-1/runs/run-1/",
    );
    expect(init).toMatchObject({
      method: "PATCH",
      body: JSON.stringify({
        output: {
          commit_push: {
            branch: "posthog-code/fix-foo",
            repository: "posthog/posthog",
            commits: RESULT.commits.map((commit) => ({
              ...commit,
              subject: "feat(desktop): show commits",
            })),
          },
        },
      }),
    });
  });

  it("abandons a stalled report and cancels its request", async () => {
    vi.useFakeTimers();
    try {
      // A connection that never answers: the commit already landed, so the
      // report must give up on its own rather than wedge the tool call.
      fetchMock.mockImplementation(() => new Promise(() => {}));
      const pending = reportTaskRunCommits({
        taskId: "task-1",
        taskRunId: "run-1",
        result: RESULT,
        message: "feat(desktop): show commits",
        env: ENV,
        envFilePath: NO_ENV_FILE,
        oauthEnvFilePath: TEST_OAUTH_ENV_FILE,
      });
      await vi.advanceTimersByTimeAsync(20_000);
      await expect(pending).resolves.toBeUndefined();

      // The deadline must also abort the request so it releases its socket
      // rather than dangling after the reporter gives up.
      const [, init] = fetchMock.mock.calls[0];
      const signal = (init as RequestInit).signal;
      expect(signal).toBeInstanceOf(AbortSignal);
      expect(signal?.aborted).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });
});
