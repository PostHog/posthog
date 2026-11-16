import { execGit } from "@posthog/git/git-exec";
import { describe, expect, it, vi } from "vitest";
import { reportTaskRunBranch } from "../signed-commit-artefacts";
import {
  gitlabMergeRequestTool,
  runGitlabMergeRequest,
} from "./gitlab-merge-request";

vi.mock("@posthog/git/git-exec", () => ({ execGit: vi.fn() }));
vi.mock("../signed-commit-artefacts", () => ({ reportTaskRunBranch: vi.fn() }));

const MR = {
  iid: 12,
  web_url: "https://gitlab.com/acme/platform/api/-/merge_requests/12",
  title: "Draft: Fix login",
  state: "opened",
  draft: true,
  source_branch: "posthog/fix-login",
  target_branch: "main",
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

function setup(responses: Response[]) {
  const fetchMock = vi.fn(async (_url: string, _init: RequestInit) => {
    const next = responses.shift();
    if (!next) throw new Error("unexpected request");
    return next;
  });
  const reportBranch = vi.fn(async () => {});
  const deps = {
    client: {
      token: "glpat-secret",
      host: "gitlab.com",
      fetch: fetchMock as unknown as typeof fetch,
    },
    projectPath: "acme/platform/api",
    currentBranch: async () => "posthog/fix-login",
    reportBranch,
  };
  return { deps, fetchMock, reportBranch };
}

describe("gitlab_merge_request tool", () => {
  it("creates a draft MR from the current branch into the project's default branch", async () => {
    const { deps, fetchMock, reportBranch } = setup([
      jsonResponse({ default_branch: "main" }),
      jsonResponse(MR, 201),
    ]);

    const result = await runGitlabMergeRequest(deps, {
      operation: "create",
      title: "Fix login",
      description: "Why: users loop on login.",
    });

    expect(result.isError).toBeUndefined();
    expect(result.content[0].text).toContain(MR.web_url);
    const [projectUrl] = fetchMock.mock.calls[0];
    expect(projectUrl).toBe(
      "https://gitlab.com/api/v4/projects/acme%2Fplatform%2Fapi",
    );
    const [createUrl, init] = fetchMock.mock.calls[1];
    expect(createUrl).toBe(
      "https://gitlab.com/api/v4/projects/acme%2Fplatform%2Fapi/merge_requests",
    );
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>).Authorization).toBe(
      "Bearer glpat-secret",
    );
    expect(JSON.parse(init.body as string)).toEqual({
      source_branch: "posthog/fix-login",
      target_branch: "main",
      title: "Draft: Fix login",
      description: "Why: users loop on login.",
    });
    expect(reportBranch).toHaveBeenCalledWith("posthog/fix-login");
  });

  it("reports the GitLab error without the token", async () => {
    const { deps } = setup([
      jsonResponse(
        {
          message: [
            "Another open merge request already exists for this source branch: !11",
          ],
        },
        409,
      ),
    ]);

    const result = await runGitlabMergeRequest(deps, {
      operation: "create",
      title: "Fix login",
      target_branch: "main",
    });

    expect(result.isError).toBe(true);
    expect(result.content[0].text).toContain("HTTP 409");
    expect(result.content[0].text).toContain("already exists");
    expect(result.content[0].text).not.toContain("glpat-secret");
  });

  it.each([
    { name: "URL", ref: MR.web_url },
    { name: "iid with !", ref: "!12" },
  ])("views an MR by $name", async ({ ref }) => {
    const { deps, fetchMock } = setup([jsonResponse(MR)]);

    const result = await runGitlabMergeRequest(deps, {
      operation: "view",
      merge_request: ref,
    });

    expect(fetchMock.mock.calls[0][0]).toBe(
      "https://gitlab.com/api/v4/projects/acme%2Fplatform%2Fapi/merge_requests/12",
    );
    expect(JSON.parse(result.content[0].text)).toMatchObject({
      web_url: MR.web_url,
      state: "opened",
      draft: true,
      source_branch: "posthog/fix-login",
      target_branch: "main",
    });
  });

  it.each([true, false])(
    "prefers an open MR for a reused branch (open: %s)",
    async (hasOpen) => {
      const closed = { ...MR, iid: 99, state: "closed" };
      const { deps } = setup([]);
      deps.client.fetch = vi.fn(async (url: string | URL | Request) => {
        const query = new URL(String(url)).searchParams;
        return jsonResponse(
          query.get("state") === "opened" ? (hasOpen ? [MR] : []) : [closed],
        );
      }) as typeof fetch;

      const result = await runGitlabMergeRequest(deps, { operation: "view" });

      expect(JSON.parse(result.content[0].text)).toMatchObject(
        hasOpen
          ? { iid: MR.iid, state: "opened" }
          : { iid: closed.iid, state: "closed" },
      );
    },
  );

  it("reports a sibling MR without changing the primary checkout branch", async () => {
    vi.stubEnv("GITLAB_TOKEN", "glpat-test");
    vi.mocked(execGit).mockResolvedValue({
      exitCode: 0,
      stdout: "https://gitlab.com/acme/platform/api.git",
      stderr: "",
    } as never);
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(jsonResponse(MR, 201));
    try {
      await gitlabMergeRequestTool.handler(
        {
          cwd: "/workspace/primary",
          taskId: "task",
          taskRunId: "run",
        } as never,
        {
          operation: "create",
          cwd: "../sibling",
          source_branch: "feature",
          target_branch: "main",
          title: "Fix",
        },
      );
      expect(reportTaskRunBranch).toHaveBeenCalledWith(
        expect.objectContaining({
          repository: "acme/platform/api",
          branch: MR.source_branch,
          updateCheckoutBranch: false,
        }),
      );
    } finally {
      fetchMock.mockRestore();
      vi.unstubAllEnvs();
    }
  });

  it("refuses an MR URL from another project without a request", async () => {
    const { deps, fetchMock } = setup([]);

    const result = await runGitlabMergeRequest(deps, {
      operation: "view",
      merge_request: "https://gitlab.com/other/repo/-/merge_requests/1",
    });

    expect(result.isError).toBe(true);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
