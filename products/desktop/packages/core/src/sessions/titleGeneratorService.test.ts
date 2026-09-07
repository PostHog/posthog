import type { FileReadClient } from "@posthog/core/files/identifiers";
import type { LlmGatewayService } from "@posthog/core/llm-gateway/llm-gateway";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TitleGeneratorService } from "./titleGeneratorService";

const readAbsoluteFile = vi.fn<FileReadClient["readAbsoluteFile"]>();
const getGithubPullRequestTitle = vi.fn();
const prompt = vi.fn();

function makeService(): TitleGeneratorService {
  const gateway = { prompt } as unknown as LlmGatewayService;
  const fileReadClient: FileReadClient = { readAbsoluteFile };
  return new TitleGeneratorService(
    gateway,
    fileReadClient,
    { getGithubPullRequestTitle },
    { error: vi.fn() },
  );
}

describe("enrichDescriptionWithFileContent", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getGithubPullRequestTitle.mockResolvedValue(null);
  });

  it("returns description unchanged when it contains real text", async () => {
    const description = "Fix the login bug";
    const result =
      await makeService().enrichDescriptionWithFileContent(description);
    expect(result).toBe(description);
    expect(readAbsoluteFile).not.toHaveBeenCalled();
  });

  it("reads text file content when description only has file tags", async () => {
    readAbsoluteFile.mockResolvedValue("const x = 1;\nexport default x;");
    const description = '1. <file path="/tmp/code.ts" />';
    const result =
      await makeService().enrichDescriptionWithFileContent(description);
    expect(result).toBe("const x = 1;\nexport default x;");
    expect(readAbsoluteFile).toHaveBeenCalledWith("/tmp/code.ts");
  });

  it("handles multiple file tags", async () => {
    readAbsoluteFile
      .mockResolvedValueOnce("file one")
      .mockResolvedValueOnce("file two");

    const description =
      '1. <file path="/tmp/a.ts" />\n2. <file path="/tmp/b.ts" />';
    const result =
      await makeService().enrichDescriptionWithFileContent(description);
    expect(result).toBe("file one\n\nfile two");
  });

  it("uses filePaths argument over parsed tags", async () => {
    readAbsoluteFile.mockResolvedValue("from explicit path");
    const description = '1. <file path="/tmp/ignored.ts" />';
    const result = await makeService().enrichDescriptionWithFileContent(
      description,
      ["/tmp/explicit.ts"],
    );
    expect(result).toBe("from explicit path");
    expect(readAbsoluteFile).toHaveBeenCalledWith("/tmp/explicit.ts");
  });

  it.each([
    {
      label: "binary file",
      description: '1. <file path="/tmp/screenshot.png" />',
      setup: () => {},
    },
    {
      label: "read throws",
      description: '1. <file path="/tmp/missing.ts" />',
      setup: () => readAbsoluteFile.mockRejectedValue(new Error("ENOENT")),
    },
    {
      label: "read returns null",
      description: '1. <file path="/tmp/empty.ts" />',
      setup: () => readAbsoluteFile.mockResolvedValue(null),
    },
  ])(
    "falls back to filename hint -- $label",
    async ({ description, setup }) => {
      setup();
      const result =
        await makeService().enrichDescriptionWithFileContent(description);
      const filename = description.match(/path="[^"]*\/([^"]+)"/)?.[1];
      expect(result).toBe(`[Attached: ${filename}]`);
    },
  );

  it.each([
    {
      label: "cloud description summary",
      description: "Attached files: pasted-text.txt",
    },
    {
      label: "numbered prompt list item",
      description: "1. [Attached files: pasted-text.txt]",
    },
  ])(
    "reads explicit file paths for attachment-only prompt -- $label",
    async ({ description }) => {
      readAbsoluteFile.mockResolvedValue(
        "Refactor the auth flow and add tests",
      );
      const result = await makeService().enrichDescriptionWithFileContent(
        description,
        ["/tmp/clip/pasted-text.txt"],
      );
      expect(result).toBe("Refactor the auth flow and add tests");
      expect(readAbsoluteFile).toHaveBeenCalledWith(
        "/tmp/clip/pasted-text.txt",
      );
    },
  );

  it("ignores explicit file paths when the prompt has real typed text", async () => {
    const description = "Fix the login bug\n\nAttached files: pasted-text.txt";
    const result = await makeService().enrichDescriptionWithFileContent(
      description,
      ["/tmp/clip/pasted-text.txt"],
    );
    expect(result).toBe(description);
    expect(readAbsoluteFile).not.toHaveBeenCalled();
  });

  it("does not strip user text that starts with 'Attached files:' but has no brackets", async () => {
    // "1. Attached files: xyz" (no brackets) is user-typed text, not a sentinel.
    const description = "1. Attached files: here is my task\n2. please fix it";
    const result = await makeService().enrichDescriptionWithFileContent(
      description,
      ["/tmp/clip/pasted-text.txt"],
    );
    expect(result).toBe(description);
    expect(readAbsoluteFile).not.toHaveBeenCalled();
  });

  it("truncates content longer than 500 chars", async () => {
    const longContent = "x".repeat(600);
    readAbsoluteFile.mockResolvedValue(longContent);
    const description = '1. <file path="/tmp/big.ts" />';
    const result =
      await makeService().enrichDescriptionWithFileContent(description);
    expect(result).toBe("x".repeat(500));
  });

  it("strips 'Attached files:' lines when checking for real text", async () => {
    readAbsoluteFile.mockResolvedValue("content");
    const description = '1. <file path="/tmp/a.ts" />\nAttached files: a.ts';
    const result =
      await makeService().enrichDescriptionWithFileContent(description);
    expect(result).toBe("content");
  });

  it("returns original description when no file paths found", async () => {
    const description = "1. \n2. ";
    const result =
      await makeService().enrichDescriptionWithFileContent(description);
    expect(result).toBe(description);
  });

  it("mixes binary and text files", async () => {
    readAbsoluteFile.mockResolvedValue("text content");
    const result = await makeService().enrichDescriptionWithFileContent("", [
      "/tmp/image.jpg",
      "/tmp/code.ts",
    ]);
    expect(result).toBe("[Attached: image.jpg]\n\ntext content");
  });

  it("returns description unchanged for folder-only input", async () => {
    const description = '<folder path="src/components" />';
    const result =
      await makeService().enrichDescriptionWithFileContent(description);
    expect(result).toBe(description);
    expect(readAbsoluteFile).not.toHaveBeenCalled();
  });

  it("reads file and drops folder for mixed file+folder input", async () => {
    readAbsoluteFile.mockResolvedValue("file body");
    const description =
      '<file path="/tmp/a.ts" /><folder path="src/components" />';
    const result =
      await makeService().enrichDescriptionWithFileContent(description);
    expect(result).toBe("file body");
    expect(readAbsoluteFile).toHaveBeenCalledTimes(1);
    expect(readAbsoluteFile).toHaveBeenCalledWith("/tmp/a.ts");
  });

  it("treats non-chip XML-like text as real content", async () => {
    const description = "<div>hello world</div>";
    const result =
      await makeService().enrichDescriptionWithFileContent(description);
    expect(result).toBe(description);
    expect(readAbsoluteFile).not.toHaveBeenCalled();
  });
});

describe("generateTitleAndSummary", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getGithubPullRequestTitle.mockResolvedValue(null);
  });

  it("truncates title to 255 chars", async () => {
    const longTitle = "A".repeat(300);
    prompt.mockResolvedValue({
      content: `TITLE: ${longTitle}\nSUMMARY: A summary`,
    });

    const result = await makeService().generateTitleAndSummary("some content");
    expect(result?.title).toHaveLength(255);
    expect(result?.summary).toBe("A summary");
  });

  it("strips surrounding quotes from title", async () => {
    prompt.mockResolvedValue({
      content: 'TITLE: "Fix login bug"\nSUMMARY: Fixing auth',
    });

    const result =
      await makeService().generateTitleAndSummary("fix the login bug");
    expect(result?.title).toBe("Fix login bug");
  });

  it("does not parse SUMMARY in a PR title as the summary", async () => {
    prompt.mockResolvedValue({
      content:
        "TITLE: Review PR #123: Fix SUMMARY: parsing\nSUMMARY: Fixing title and summary parsing.",
    });

    const result = await makeService().generateTitleAndSummary(
      '<github_pr number="123" title="Fix SUMMARY: parsing" url="https://github.com/org/repo/pull/123" />',
    );

    expect(result).toEqual({
      title: "Review PR #123: Fix SUMMARY: parsing",
      summary: "Fixing title and summary parsing.",
    });
  });

  it("only asks the model for a summary for existing GitHub PRs", async () => {
    prompt.mockResolvedValue({
      content: "SUMMARY: Reviewing the existing pull request.",
    });

    const result = await makeService().generateTitleAndSummary(
      '<github_pr number="123" title="Fix login redirect" url="https://github.com/org/repo/pull/123" />',
    );

    expect(result?.title).toBe("Review PR #123: Fix login redirect");
    expect(prompt).toHaveBeenCalledWith(
      [
        expect.objectContaining({
          content: expect.stringContaining("ONLY generate a summary"),
        }),
      ],
      expect.objectContaining({
        system: expect.not.stringContaining("TITLE:"),
      }),
    );
  });

  it("keeps a numbered standalone PR deterministic", async () => {
    prompt.mockResolvedValue({ content: "SUMMARY: Reviewing the PR." });

    const result = await makeService().generateTitleAndSummary(
      '1. <github_pr number="123" title="Fix login redirect" url="https://github.com/org/repo/pull/123" />',
    );

    expect(result?.title).toBe("Review PR #123: Fix login redirect");
  });

  it("uses the model for a broader task containing one PR", async () => {
    prompt.mockResolvedValue({
      content:
        "TITLE: Audit auth changes in PR #123\nSUMMARY: Auditing authentication changes.",
    });

    const result = await makeService().generateTitleAndSummary(
      'Audit the auth changes in <github_pr number="123" title="Fix login redirect" url="https://github.com/org/repo/pull/123" />',
    );

    expect(result?.title).toBe("Audit auth changes in PR #123");
    expect(prompt).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ system: expect.stringContaining("TITLE:") }),
    );
  });

  it("resolves all PR placeholders before modeling a multi-PR task", async () => {
    getGithubPullRequestTitle
      .mockResolvedValueOnce("Fix login redirect")
      .mockResolvedValueOnce("Add session expiry");
    prompt.mockResolvedValue({
      content:
        "TITLE: Compare PR #123 and #456\nSUMMARY: Comparing two authentication pull requests.",
    });

    const result = await makeService().generateTitleAndSummary(
      'Compare <github_pr number="123" title="Loading..." url="https://github.com/org/repo/pull/123" /> with <github_pr number="456" title="Loading..." url="https://github.com/org/repo/pull/456" />',
      { resolveGithubPrTitles: true },
    );

    expect(result?.title).toBe("Compare PR #123 and #456");
    expect(getGithubPullRequestTitle).toHaveBeenCalledTimes(2);
    expect(prompt).toHaveBeenCalledWith(
      [
        expect.objectContaining({
          content: expect.stringMatching(
            /title="Fix login redirect"[\s\S]*title="Add session expiry"/,
          ),
        }),
      ],
      expect.objectContaining({ system: expect.stringContaining("TITLE:") }),
    );
  });

  it("uses the existing GitHub PR title when the model omits it", async () => {
    prompt.mockResolvedValue({
      content:
        "TITLE: Review pull request #123\nSUMMARY: Reviewing the existing pull request.",
    });

    const result = await makeService().generateTitleAndSummary(
      '<github_pr number="123" title="Fix login redirect" url="https://github.com/org/repo/pull/123" />',
    );

    expect(result).toEqual({
      title: "Review PR #123: Fix login redirect",
      summary: "Reviewing the existing pull request.",
    });
  });

  it("decodes the PR title from structured metadata", async () => {
    prompt.mockResolvedValue({ content: "SUMMARY: Reviewing the PR." });

    const result = await makeService().generateTitleAndSummary(
      '<github_pr number="123" title="Fix &quot;login&quot; &amp; redirect" url="https://github.com/org/repo/pull/123" />',
    );

    expect(result?.title).toBe('Review PR #123: Fix "login" & redirect');
  });

  it.each(["Loading...", "Loading…"])(
    "resolves the unresolved GitHub PR title %s",
    async (title) => {
      getGithubPullRequestTitle.mockResolvedValue(
        "fix: enforce PR titles in task names",
      );
      prompt.mockResolvedValue({
        content: "SUMMARY: Reviewing the existing pull request.",
      });

      const result = await makeService().generateTitleAndSummary(
        `<github_pr number="123" title="${title}" url="https://github.com/org/repo/pull/123" />`,
        { resolveGithubPrTitles: true },
      );

      expect(result?.title).toBe(
        "Review PR #123: fix: enforce PR titles in task names",
      );
      expect(getGithubPullRequestTitle).toHaveBeenCalledWith({
        owner: "org",
        repo: "repo",
        number: 123,
      });
      expect(prompt).toHaveBeenCalledWith(
        expect.anything(),
        expect.objectContaining({
          system: expect.not.stringContaining("TITLE:"),
        }),
      );
    },
  );

  it.each([
    { name: "returns no title", resolve: () => Promise.resolve(null) },
    {
      name: "rejects",
      resolve: () => Promise.reject(new Error("IPC disconnected")),
    },
  ])(
    "uses a safe PR fallback when GitHub lookup $name",
    async ({ resolve }) => {
      getGithubPullRequestTitle.mockImplementation(resolve);
      prompt.mockResolvedValue({
        content: "SUMMARY: Reviewing the existing pull request.",
      });

      const result = await makeService().generateTitleAndSummary(
        '<github_pr number="123" title="Loading..." url="https://github.com/org/repo/pull/123" />',
        { resolveGithubPrTitles: true },
      );

      expect(result).toEqual({
        title: "Review PR #123",
        summary: "Reviewing the existing pull request.",
      });
    },
  );

  it("does not resolve PR metadata from untrusted content", async () => {
    prompt.mockResolvedValue({ content: "SUMMARY: Reviewing the PR." });

    const result = await makeService().generateTitleAndSummary(
      '<github_pr number="123" title="Loading..." url="https://github.com/private/repo/pull/123" />',
    );

    expect(getGithubPullRequestTitle).not.toHaveBeenCalled();
    expect(result?.title).toBe("Review PR #123");
  });

  it("returns null on error", async () => {
    prompt.mockRejectedValue(new Error("network error"));
    const result = await makeService().generateTitleAndSummary("some content");
    expect(result).toBeNull();
  });
});
