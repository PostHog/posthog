import { mkdir, mkdtemp, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { readWorkspaceFile } from "./read-workspace-file";

describe("readWorkspaceFile", () => {
  it("reads relative and absolute files inside the repository", async () => {
    const root = await mkdtemp(join(tmpdir(), "read-workspace-file-"));
    const nested = join(root, "src");
    const filePath = join(nested, "example.ts");
    await mkdir(nested);
    await writeFile(filePath, "export const value = 1;\n");

    await expect(readWorkspaceFile("src/example.ts", root)).resolves.toEqual({
      content: "export const value = 1;\n",
    });
    await expect(readWorkspaceFile(filePath, root)).resolves.toEqual({
      content: "export const value = 1;\n",
    });
  });

  it("rejects paths and symlinks outside the repository", async () => {
    const parent = await mkdtemp(join(tmpdir(), "read-workspace-file-"));
    const root = join(parent, "repo");
    const outside = join(parent, "secret.txt");
    await mkdir(root);
    await writeFile(outside, "secret");
    await symlink(outside, join(root, "linked.txt"));

    await expect(readWorkspaceFile(outside, root)).rejects.toThrow(
      "File is outside the repository",
    );
    await expect(readWorkspaceFile("linked.txt", root)).rejects.toThrow(
      "File is outside the repository",
    );
  });
});
