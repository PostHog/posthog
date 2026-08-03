import { chmod, mkdir, mkdtemp, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { forceRemove, parseGithubUrl } from "./utils";

async function fileExists(p: string): Promise<boolean> {
  try {
    await stat(p);
    return true;
  } catch {
    return false;
  }
}

describe("forceRemove", () => {
  let workDir: string | undefined;

  afterEach(async () => {
    if (workDir) {
      await forceRemove(workDir).catch(() => {});
      workDir = undefined;
    }
  });

  it("is a no-op for a missing path", async () => {
    workDir = await mkdtemp(path.join(tmpdir(), "posthog-force-remove-"));
    await expect(
      forceRemove(path.join(workDir, "missing")),
    ).resolves.toBeUndefined();
  });

  it.each([
    {
      name: "writable tree",
      setup: async (target: string) => {
        await mkdir(path.join(target, "nested"), { recursive: true });
        await writeFile(path.join(target, "nested", "file.txt"), "x");
      },
    },
    {
      name: "read-only directories (Go module cache shape)",
      setup: async (target: string) => {
        const inner = path.join(target, "yaml.v3@v3.0.1", ".github");
        await mkdir(inner, { recursive: true });
        await writeFile(path.join(inner, "workflow.yml"), "on: push\n");
        await chmod(path.join(target, "yaml.v3@v3.0.1", ".github"), 0o555);
        await chmod(path.join(target, "yaml.v3@v3.0.1"), 0o555);
        // Confirm plain fs.rm cannot remove it.
        await expect(
          rm(target, { recursive: true, force: true }),
        ).rejects.toMatchObject({ code: "EACCES" });
        // Restore read-only state so forceRemove starts clean.
        await chmod(path.join(target, "yaml.v3@v3.0.1"), 0o555);
        await chmod(path.join(target, "yaml.v3@v3.0.1", ".github"), 0o555);
      },
    },
  ])("removes a $name", async ({ setup }) => {
    workDir = await mkdtemp(path.join(tmpdir(), "posthog-force-remove-"));
    const target = path.join(workDir, "tree");
    await mkdir(target);
    await setup(target);

    await forceRemove(target);

    expect(await fileExists(target)).toBe(false);
  });
});

describe("parseGithubUrl", () => {
  describe("repo", () => {
    it.each([
      // HTTPS canonical forms
      ["https://github.com/PostHog/code.git", "PostHog", "code"],
      ["https://github.com/PostHog/code", "PostHog", "code"],
      ["https://github.com/PostHog/code/", "PostHog", "code"],
      ["https://github.com/PostHog/code.git/", "PostHog", "code"],
      ["http://github.com/PostHog/code.git", "PostHog", "code"],
      ["https://user:token@github.com/PostHog/code.git", "PostHog", "code"],
      // SCP-style SSH
      ["git@github.com:PostHog/code.git", "PostHog", "code"],
      ["git@github.com:PostHog/code", "PostHog", "code"],
      // ssh:// SSH variants
      ["ssh://git@github.com/PostHog/code.git", "PostHog", "code"],
      ["ssh://github.com/PostHog/code.git", "PostHog", "code"],
      ["ssh://git@ssh.github.com:443/PostHog/code.git", "PostHog", "code"],
      [
        "ssh://git@ssh.github.com:443/buildingapplications/bilt-landing.git",
        "buildingapplications",
        "bilt-landing",
      ],
      ["ssh://git@github.com:22/PostHog/code.git", "PostHog", "code"],
      // Other protocols
      ["git://github.com/PostHog/code.git", "PostHog", "code"],
      ["git+https://github.com/PostHog/code.git", "PostHog", "code"],
      ["git+ssh://git@github.com/PostHog/code.git", "PostHog", "code"],
      // Whitespace + shorthand
      ["  https://github.com/PostHog/code.git\n", "PostHog", "code"],
      ["\thttps://github.com/PostHog/code.git", "PostHog", "code"],
      ["PostHog/code", "PostHog", "code"],
      // Deep links resolve to the underlying repo
      [
        "https://github.com/PostHog/code/blob/main/README.md",
        "PostHog",
        "code",
      ],
      ["https://github.com/PostHog/code/tree/main", "PostHog", "code"],
      ["https://github.com/PostHog/code/commit/abc123", "PostHog", "code"],
      ["https://github.com/PostHog/code/wiki", "PostHog", "code"],
      ["https://github.com/PostHog/code/actions", "PostHog", "code"],
      [
        "https://github.com/PostHog/code/releases/tag/v1.0.0",
        "PostHog",
        "code",
      ],
      // Mixed-case host (case in path is preserved)
      ["git@GitHub.com:PostHog/Code.git", "PostHog", "Code"],
      ["https://GITHUB.COM/PostHog/code.git", "PostHog", "code"],
      ["HTTPS://github.com/PostHog/code.git", "PostHog", "code"],
      // Query strings + fragments
      ["https://github.com/PostHog/code.git?ref=main", "PostHog", "code"],
      ["https://github.com/PostHog/code#readme", "PostHog", "code"],
      // Special characters
      ["https://github.com/post-hog/my-cool-repo", "post-hog", "my-cool-repo"],
      ["https://github.com/PostHog/dotted.repo", "PostHog", "dotted.repo"],
      ["https://github.com/Post_Hog/repo_name", "Post_Hog", "repo_name"],
      ["https://github.com/123/456", "123", "456"],
    ])("parses %s", (url, owner, repo) => {
      expect(parseGithubUrl(url)).toEqual({ kind: "repo", owner, repo });
    });
  });

  describe("issue", () => {
    it.each([
      [
        "https://github.com/PostHog/posthog/issues/57021",
        "PostHog",
        "posthog",
        57021,
      ],
      ["http://github.com/PostHog/code/issues/1", "PostHog", "code", 1],
      ["  https://github.com/PostHog/code/issues/7\n", "PostHog", "code", 7],
      [
        "https://github.com/PostHog/code/issues/42?foo=bar",
        "PostHog",
        "code",
        42,
      ],
      [
        "https://github.com/PostHog/code/issues/42#issuecomment-1",
        "PostHog",
        "code",
        42,
      ],
      ["https://GITHUB.COM/PostHog/code/issues/42", "PostHog", "code", 42],
      [
        "https://github.com/PostHog/code/issues/999999",
        "PostHog",
        "code",
        999999,
      ],
    ])("parses %s", (url, owner, repo, number) => {
      expect(parseGithubUrl(url)).toEqual({
        kind: "issue",
        owner,
        repo,
        number,
      });
    });
  });

  describe("pr", () => {
    it.each([
      ["https://github.com/PostHog/code/pull/42", "PostHog", "code", 42],
      ["http://github.com/PostHog/code/pull/1", "PostHog", "code", 1],
      ["  https://github.com/PostHog/code/pull/7\n", "PostHog", "code", 7],
      // Sub-pages and tabs
      ["https://github.com/PostHog/code/pull/42/files", "PostHog", "code", 42],
      [
        "https://github.com/PostHog/code/pull/42/commits/abc123",
        "PostHog",
        "code",
        42,
      ],
      ["https://github.com/PostHog/code/pull/42/checks", "PostHog", "code", 42],
      // Query strings + fragments
      [
        "https://github.com/PostHog/code/pull/42?diff=split",
        "PostHog",
        "code",
        42,
      ],
      [
        "https://github.com/PostHog/code/pull/42#discussion_r123",
        "PostHog",
        "code",
        42,
      ],
      ["https://GITHUB.COM/PostHog/code/pull/42", "PostHog", "code", 42],
      [
        "https://github.com/post-hog/my-repo/pull/42",
        "post-hog",
        "my-repo",
        42,
      ],
      [
        "https://github.com/PostHog/code/pull/999999",
        "PostHog",
        "code",
        999999,
      ],
    ])("parses %s", (url, owner, repo, number) => {
      expect(parseGithubUrl(url)).toEqual({ kind: "pr", owner, repo, number });
    });
  });

  describe("rejects", () => {
    it.each<string | null | undefined>([
      // Empty / nullish
      "",
      "   ",
      "\t\n",
      null,
      undefined,
      // Non-URL strings
      "not-a-url",
      "PostHog",
      // Wrong host
      "https://gitlab.com/PostHog/code.git",
      "https://example.com/PostHog/code.git",
      "git@gitlab.com:PostHog/code.git",
      "git@my-alias:PostHog/code.git",
      "https://raw.githubusercontent.com/PostHog/code/main/README.md",
      "https://api.github.com/repos/PostHog/code",
      "file:///path/to/repo",
      // Missing repo
      "https://github.com/PostHog",
      // Multiple / leading slashes
      "https://github.com//PostHog/code.git",
      "https://github.com/PostHog//code.git",
      "https://github.com//PostHog/code/pull/42",
      "https://github.com/PostHog/code//pull/42",
      "https://github.com/PostHog/code/pull//42",
      // Bad ref number
      "https://github.com/PostHog/code/issues/abc",
      "https://github.com/PostHog/code/issues/0",
      "https://github.com/PostHog/code/issues/-1",
      "https://github.com/PostHog/code/issues/42.5",
      "https://github.com/PostHog/code/issues/",
      "https://github.com/PostHog/code/pull/abc",
      "https://github.com/PostHog/code/pull/0",
      "https://github.com/PostHog/code/pull/-1",
      "https://github.com/PostHog/code/pull/42.5",
      "https://github.com/PostHog/code/pull/",
    ])("returns null for %s", (url) => {
      expect(parseGithubUrl(url)).toBeNull();
    });
  });
});
