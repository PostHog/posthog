import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { HookInput } from "@anthropic-ai/claude-agent-sdk";
import { afterAll, beforeAll, describe, expect, test } from "vitest";
import { createMemoryReadHook, type MemoryRead } from "./memory-reads";

describe("createMemoryReadHook", () => {
  let projectsDir: string;

  beforeAll(() => {
    projectsDir = fs.mkdtempSync(path.join(os.tmpdir(), "memory-reads-"));
    for (const [slug, files] of Object.entries({
      "-tmp-workspace": ["MEMORY.md", "feedback_test_runner.md", "shared.md"],
      "-tmp-other": ["shared.md"],
    })) {
      const dir = path.join(projectsDir, slug, "memory");
      fs.mkdirSync(dir, { recursive: true });
      for (const file of files) fs.writeFileSync(path.join(dir, file), "x");
    }
  });

  afterAll(() => {
    fs.rmSync(projectsDir, { recursive: true, force: true });
  });

  const memoryDir = (slug: string) => path.join(projectsDir, slug, "memory");
  const runner = { slug: "-tmp-workspace", file: "feedback_test_runner.md" };

  test.each<{
    name: string;
    tool: string;
    input: () => unknown;
    response?: () => unknown;
    expected: { slug: string; file: string }[];
  }>([
    {
      name: "Read with the absolute path",
      tool: "Read",
      input: () => ({
        file_path: path.join(
          memoryDir("-tmp-workspace"),
          "feedback_test_runner.md",
        ),
      }),
      expected: [runner],
    },
    {
      name: "Bash with a relative path",
      tool: "Bash",
      input: () => ({
        command: "cd /tmp/x && cat memory/feedback_test_runner.md",
      }),
      expected: [runner],
    },
    {
      name: "Grep on the memory directory, from the response",
      tool: "Grep",
      input: () => ({ pattern: "zebra", path: memoryDir("-tmp-workspace") }),
      response: () => ({ filenames: ["feedback_test_runner.md"] }),
      expected: [runner],
    },
    {
      name: "Grep elsewhere whose response names the file",
      tool: "Grep",
      input: () => ({ pattern: "zebra", path: "/tmp/repo" }),
      response: () => ({ filenames: ["docs/feedback_test_runner.md"] }),
      expected: [],
    },
    {
      name: "a path that pins one of two projects sharing a file name",
      tool: "Read",
      input: () => ({
        file_path: path.join(memoryDir("-tmp-other"), "shared.md"),
      }),
      expected: [{ slug: "-tmp-other", file: "shared.md" }],
    },
    {
      name: "a write tool",
      tool: "Write",
      input: () => ({
        file_path: path.join(
          memoryDir("-tmp-workspace"),
          "feedback_test_runner.md",
        ),
      }),
      expected: [],
    },
    {
      name: "a tool that cannot read files",
      tool: "mcp__posthog-code-tools__task_summary_update",
      input: () => ({ summary: "The bird is in feedback_test_runner.md" }),
      expected: [],
    },
    {
      name: "the index file",
      tool: "Read",
      input: () => ({
        file_path: path.join(memoryDir("-tmp-workspace"), "MEMORY.md"),
      }),
      expected: [],
    },
    {
      name: "a longer file name that contains a memory file name",
      tool: "Bash",
      input: () => ({ command: "cat old_feedback_test_runner.md" }),
      expected: [],
    },
  ])("$name", async ({ tool, input, response, expected }) => {
    const reads: MemoryRead[] = [];
    const hook = createMemoryReadHook((read) => reads.push(read), projectsDir);

    await hook(
      {
        session_id: "s",
        transcript_path: "/tmp/t",
        cwd: "/tmp",
        hook_event_name: "PostToolUse",
        tool_name: tool,
        tool_input: input(),
        tool_response: response?.(),
        tool_use_id: "toolu_1",
        agent_id: "agent_1",
      } as HookInput,
      "toolu_1",
      { signal: new AbortController().signal },
    );

    expect(reads).toEqual(
      expected.map((memoryFile) => ({
        ...memoryFile,
        tool,
        toolCallId: "toolu_1",
        agentId: "agent_1",
      })),
    );
  });
});
