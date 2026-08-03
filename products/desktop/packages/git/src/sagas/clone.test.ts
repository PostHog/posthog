import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { createGitClient } from "../client";
import { CloneSaga } from "./clone";

describe("CloneSaga", () => {
  let testRoot: string;
  let sourcePath: string;
  let targetPath: string;

  beforeEach(async () => {
    testRoot = await mkdtemp(path.join(tmpdir(), "posthog-code-clone-"));
    sourcePath = path.join(testRoot, "source");
    targetPath = path.join(testRoot, "target");
    await mkdir(sourcePath);

    const git = createGitClient(sourcePath);
    await git.init(["--initial-branch", "main"]);
    await git.addConfig("user.name", "PostHog Code Test");
    await git.addConfig("user.email", "posthog-code-test@example.com");
    await git.addConfig("commit.gpgsign", "false");

    await writeFile(path.join(sourcePath, "first.txt"), "first\n");
    await git.add(["first.txt"]);
    await git.commit("first");

    await writeFile(path.join(sourcePath, "second.txt"), "second\n");
    await git.add(["second.txt"]);
    await git.commit("second");

    await git.checkoutLocalBranch("feature");
    await writeFile(path.join(sourcePath, "feature.txt"), "feature\n");
    await git.add(["feature.txt"]);
    await git.commit("feature");
    await git.addTag("source-tag");
  });

  afterEach(async () => {
    await rm(testRoot, { recursive: true, force: true });
  });

  it("clones the requested branch with one commit and no tags", async () => {
    const cleanRemoteUrl = "https://github.com/PostHog/posthog.git";
    const result = await new CloneSaga().run({
      repoUrl: cleanRemoteUrl,
      targetPath,
      branch: "feature",
      shallow: true,
      env: {
        GIT_CONFIG_COUNT: "1",
        GIT_CONFIG_KEY_0: `url.${pathToFileURL(sourcePath).href}.insteadOf`,
        GIT_CONFIG_VALUE_0: cleanRemoteUrl,
      },
    });

    if (!result.success) {
      throw new Error(result.error);
    }
    const git = createGitClient(targetPath);
    await expect(git.revparse(["--abbrev-ref", "HEAD"])).resolves.toBe(
      "feature",
    );
    await expect(git.revparse(["--is-shallow-repository"])).resolves.toBe(
      "true",
    );
    await expect(git.raw(["rev-list", "--count", "HEAD"])).resolves.toBe("1");
    await expect(git.tags()).resolves.toMatchObject({ all: [] });
    await expect(
      git.remote(["get-url", "origin"]).then((origin) => origin?.trim()),
    ).resolves.toBe(cleanRemoteUrl);
  });
});
