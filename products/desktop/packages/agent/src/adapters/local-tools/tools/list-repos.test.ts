import { beforeEach, describe, expect, it, vi } from "vitest";

const execGh = vi.fn();

vi.mock("@posthog/git/gh", () => ({
  execGh: (...args: unknown[]) => execGh(...args),
}));

vi.mock("../../../utils/github-token", () => ({
  resolveGithubToken: vi.fn(() => undefined),
}));

const { listReposTool } = await import("./list-repos");

const CTX = { cwd: "/repo", token: "ghs_installation" };

const ok = (stdout: string) => ({ stdout, stderr: "", exitCode: 0 });
const fail = (stderr: string) => ({ stdout: "", stderr, exitCode: 1 });

const installationPayload = (
  repos: { full_name: string; description?: string; archived?: boolean }[],
) => JSON.stringify({ total_count: repos.length, repositories: repos });

/** Routes `gh repo list` and `gh api` to separate canned responses. */
function mockGh(responses: {
  repoList: ReturnType<typeof ok> | ReturnType<typeof fail>;
  api?: ReturnType<typeof ok> | ReturnType<typeof fail>;
}): void {
  execGh.mockImplementation((args: string[]) =>
    args[0] === "repo"
      ? responses.repoList
      : (responses.api ?? fail("HTTP 403: Resource not accessible")),
  );
}

const apiCalls = (): string[][] =>
  execGh.mock.calls
    .map(([args]) => args as string[])
    .filter((a) => a[0] === "api");

describe("list_repos tool", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // `gh repo list` enumerates the *user* behind the token. An installation token
  // has no user, so it comes back empty (or refused) however many repositories
  // the project connected — the bug this fallback exists for.
  it.each([
    { name: "the user listing is empty", repoList: ok("[]") },
    {
      name: "the user listing is refused",
      repoList: fail("Resource not accessible by integration"),
    },
  ])("lists the installation's repos when $name", async ({ repoList }) => {
    mockGh({
      repoList,
      api: ok(
        installationPayload([
          { full_name: "PostHog/posthog", description: "the hog" },
          { full_name: "PostHog/posthog.com" },
          { full_name: "PostHog/retired", archived: true },
        ]),
      ),
    });

    const result = await listReposTool.handler(CTX, {});

    expect(result.isError).toBeUndefined();
    expect(result.content[0].text).toBe(
      "PostHog/posthog: the hog\nPostHog/posthog.com",
    );
  });

  it("applies the owner and query filters to the installation's repos", async () => {
    mockGh({
      repoList: ok("[]"),
      api: ok(
        installationPayload([
          { full_name: "PostHog/posthog-foss" },
          { full_name: "PostHog/charts" },
          { full_name: "OtherOrg/posthog-plugin" },
        ]),
      ),
    });

    const result = await listReposTool.handler(CTX, {
      owner: "posthog",
      query: "foss",
    });

    expect(result.content[0].text).toBe("PostHog/posthog-foss");
  });

  it("does not reach for the installation endpoint when the user listing worked", async () => {
    mockGh({
      repoList: ok(
        JSON.stringify([{ nameWithOwner: "me/thing", description: null }]),
      ),
    });

    const result = await listReposTool.handler(CTX, {});

    expect(result.content[0].text).toBe("me/thing");
    expect(apiCalls()).toHaveLength(0);
  });

  it("reports the original gh error when neither listing works", async () => {
    mockGh({
      repoList: fail("gh: authentication required"),
      api: fail("HTTP 403: Resource not accessible by personal access token"),
    });

    const result = await listReposTool.handler(CTX, {});

    expect(result.isError).toBe(true);
    expect(result.content[0].text).toContain("authentication required");
    expect(result.content[0].text).not.toContain("HTTP 403");
  });

  it("reports no repositories when both listings come back empty", async () => {
    mockGh({ repoList: ok("[]"), api: ok(installationPayload([])) });

    const result = await listReposTool.handler(CTX, {});

    expect(result.isError).toBeUndefined();
    expect(result.content[0].text).toBe("No repositories found.");
  });
});
