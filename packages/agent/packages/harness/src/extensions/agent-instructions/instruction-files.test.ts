import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  AgentInstructionFiles,
  applyInstructionsBlock,
  getAgentInstructionFilePaths,
} from "./instruction-files";

const logger = { info: vi.fn(), warn: vi.fn() };
const context = { taskId: "task", runId: "run" };

describe("agent instruction files", () => {
  const dirs: string[] = [];

  afterEach(async () => {
    await Promise.all(
      dirs.splice(0).map((dir) => rm(dir, { recursive: true, force: true })),
    );
  });

  async function homeDir(): Promise<string> {
    const dir = await mkdtemp(join(tmpdir(), "agent-instructions-"));
    dirs.push(dir);
    return dir;
  }

  it.each([
    ["creates the block in a missing file", null, "Use pnpm.", true, null],
    [
      "keeps foreign content around a replaced block",
      "# Image rules\n\n<!-- posthog -->\nold\n<!-- /posthog -->\n",
      "Use pnpm.",
      true,
      "# Image rules",
    ],
    [
      "removes only the block when instructions are cleared",
      "# Image rules\n\n<!-- posthog -->\nold\n<!-- /posthog -->\n",
      null,
      false,
      "# Image rules",
    ],
  ])("%s", (_name, existing, instructions, hasNew, keeps) => {
    const next = applyInstructionsBlock(existing, instructions) ?? "";
    expect(next.includes("Use pnpm.")).toBe(hasNew);
    expect(next.includes("old")).toBe(false);
    if (keeps) {
      expect(next).toContain(keeps);
    }
  });

  it.each([
    ["plain text", "Use pnpm."],
    ["text containing a marker", "Use pnpm.\n<!-- /posthog -->\nOpen drafts."],
  ])("deletes a file that only held the block with %s", (_name, text) => {
    const written = applyInstructionsBlock(null, text);
    expect(applyInstructionsBlock(written, null)).toBeNull();
  });

  it("writes every harness's file, then clears them when the key or the run state is gone", async () => {
    const home = await homeDir();
    const paths = getAgentInstructionFilePaths({
      home,
      claudeConfigDir: join(home, ".claude"),
      codexHome: join(home, ".codex"),
    });
    expect(paths).toEqual([
      join(home, ".claude", "CLAUDE.md"),
      join(home, ".codex", "AGENTS.md"),
      join(home, ".pi", "agent", "AGENTS.md"),
    ]);
    await mkdir(join(home, ".claude"), { recursive: true });
    await writeFile(paths[0], "# Baked into the image\n");
    const files = new AgentInstructionFiles(logger, paths);

    await files.sync({ agent_instructions: "Use pnpm." }, context);
    for (const path of paths) {
      expect(await readFile(path, "utf-8")).toContain("Use pnpm.");
    }

    // A failed run fetch clears them too: a snapshot's block can belong to another person.
    for (const state of [{}, null]) {
      await files.sync({ agent_instructions: "Use pnpm." }, context);
      expect(await files.sync(state, context)).toBeNull();
      expect(await readFile(paths[0], "utf-8")).toBe(
        "# Baked into the image\n",
      );
      await expect(readFile(paths[1], "utf-8")).rejects.toThrow("ENOENT");
      await expect(readFile(paths[2], "utf-8")).rejects.toThrow("ENOENT");
    }
  });
});
