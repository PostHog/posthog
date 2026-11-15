import type {
  BashToolCallEvent,
  ExtensionAPI,
  ExtensionFactory,
  ToolCallEvent,
} from "@earendil-works/pi-coding-agent";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createRtkExtension } from "./extension";

type ToolCallHandler = (
  event: ToolCallEvent,
  context: { signal?: AbortSignal },
) => Promise<void>;

function execResult(
  code: number,
  stdout = "",
  killed = false,
): { code: number; stdout: string; killed: boolean } {
  return { code, stdout, killed };
}

async function loadExtension(
  exec: ReturnType<typeof vi.fn>,
): Promise<ToolCallHandler> {
  const handlers = new Map<string, ToolCallHandler>();
  const extension: ExtensionFactory = createRtkExtension();

  await extension({
    exec,
    on: (event: string, handler: ToolCallHandler) => {
      handlers.set(event, handler);
    },
  } as unknown as ExtensionAPI);

  const handler = handlers.get("tool_call");
  if (!handler) {
    throw new Error("RTK did not register a tool call handler");
  }
  return handler;
}

function bashCall(command: string): BashToolCallEvent {
  return {
    type: "tool_call",
    toolName: "bash",
    toolCallId: "call-1",
    input: { command },
  };
}

beforeEach(() => {
  vi.stubEnv("POSTHOG_RTK", "1");
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("createRtkExtension", () => {
  it.each([
    ["a standard rewrite", 0, "rtk git status"],
    ["an advisory rewrite", 3, "rtk git status"],
  ])("uses %s from rtk", async (_label, code, rewritten) => {
    const exec = vi
      .fn()
      .mockResolvedValueOnce(execResult(0, "rtk 0.43.0"))
      .mockResolvedValueOnce(execResult(code, rewritten));
    const handler = await loadExtension(exec);
    const event = bashCall("git status");

    await handler(event, {});

    expect(event.input.command).toBe(rewritten);
    expect(exec).toHaveBeenLastCalledWith(
      "rtk",
      ["rewrite", "git status"],
      expect.objectContaining({ timeout: 2_000 }),
    );
  });

  it.each([
    ["has no rewrite", execResult(1)],
    ["returns empty output", execResult(0)],
    ["returns the original command", execResult(0, "git status")],
    ["is killed", execResult(0, "rtk git status", true)],
  ])("keeps the original command when rtk %s", async (_label, result) => {
    const exec = vi
      .fn()
      .mockResolvedValueOnce(execResult(0, "rtk 0.43.0"))
      .mockResolvedValueOnce(result);
    const handler = await loadExtension(exec);
    const event = bashCall("git status");

    await handler(event, {});

    expect(event.input.command).toBe("git status");
  });

  it("does not start rtk when POSTHOG_RTK=0", async () => {
    vi.stubEnv("POSTHOG_RTK", "0");
    const exec = vi.fn();
    const handlers = new Map<string, ToolCallHandler>();

    await createRtkExtension()({
      exec,
      on: (event: string, handler: ToolCallHandler) => {
        handlers.set(event, handler);
      },
    } as unknown as ExtensionAPI);

    expect(exec).not.toHaveBeenCalled();
    expect(handlers.get("tool_call")).toBeUndefined();
  });

  it.each([
    ["is unavailable", execResult(1)],
    ["is too old", execResult(0, "rtk 0.22.0")],
  ])("does not register when rtk %s", async (_label, version) => {
    const handlers = new Map<string, ToolCallHandler>();
    const extension = createRtkExtension();

    await extension({
      exec: vi.fn().mockResolvedValue(version),
      on: (event: string, handler: ToolCallHandler) => {
        handlers.set(event, handler);
      },
    } as unknown as ExtensionAPI);

    expect(handlers.get("tool_call")).toBeUndefined();
  });

  it("does not rewrite an already wrapped command", async () => {
    const exec = vi.fn().mockResolvedValue(execResult(0, "rtk 0.43.0"));
    const handler = await loadExtension(exec);
    const wrapped = bashCall("rtk git status");

    await handler(wrapped, {});

    expect(wrapped.input.command).toBe("rtk git status");
    expect(exec).toHaveBeenCalledTimes(1);
  });
});
