import type {
  ExtensionAPI,
  ExtensionContext,
  ToolCallEvent,
} from "@earendil-works/pi-coding-agent";
import { describe, expect, it, vi } from "vitest";
import { createCurrentWorkExtension } from "./extension";

type ToolCallHandler = (
  event: ToolCallEvent,
  context: ExtensionContext,
) => unknown;

type LifecycleHandler = (event: unknown, context: ExtensionContext) => unknown;

type EmptyRenderer = () => { render: (width: number) => string[] };

type CurrentWorkTool = {
  renderCall: EmptyRenderer;
  renderResult: EmptyRenderer;
  renderShell: "self";
  execute: (
    toolCallId: string,
    params: { status: string },
    signal: AbortSignal | undefined,
    onUpdate: undefined,
    context: ExtensionContext,
  ) => Promise<unknown>;
};

function toolCall(
  toolName: string,
  input: Record<string, unknown> = {},
): ToolCallEvent {
  return {
    type: "tool_call",
    toolCallId: "call-1",
    toolName,
    input,
  } as ToolCallEvent;
}

function setup(mode: "rpc" | "tui" = "rpc") {
  const handlers = new Map<string, ToolCallHandler | LifecycleHandler>();
  const setStatus = vi.fn();
  const setWorkingMessage = vi.fn();
  let currentWorkTool: CurrentWorkTool | undefined;
  const context = {
    mode,
    ui: { setStatus, setWorkingMessage },
  } as unknown as ExtensionContext;

  createCurrentWorkExtension()({
    on: (event: string, handler: ToolCallHandler | LifecycleHandler) => {
      handlers.set(event, handler);
    },
    registerTool: (tool: CurrentWorkTool) => {
      currentWorkTool = tool;
    },
  } as unknown as ExtensionAPI);

  const currentWorkHandler = handlers.get("tool_call") as ToolCallHandler;
  const beforeAgentStartHandler = handlers.get(
    "before_agent_start",
  ) as LifecycleHandler;
  const agentEndHandler = handlers.get("agent_end") as LifecycleHandler;
  const agentStartHandler = handlers.get("agent_start") as LifecycleHandler;
  const settledHandler = handlers.get("agent_settled") as LifecycleHandler;
  if (
    !currentWorkTool ||
    !currentWorkHandler ||
    !beforeAgentStartHandler ||
    !agentStartHandler ||
    !agentEndHandler ||
    !settledHandler
  ) {
    throw new Error("Current-work extension was not initialized");
  }

  return {
    agentEndHandler,
    agentStartHandler,
    beforeAgentStartHandler,
    context,
    currentWorkHandler,
    currentWorkTool,
    settledHandler,
    setStatus,
    setWorkingMessage,
  };
}

describe("current-work extension", () => {
  it("injects a set_current_work reminder after the user message at agent start", () => {
    const extension = setup();

    const result = extension.beforeAgentStartHandler(
      {} as never,
      extension.context,
    ) as {
      message?: { customType: string; content: string; display: boolean };
    };

    expect(result.message?.customType).toBe("current-work-reminder");
    expect(result.message?.content).toBe(
      "Set the visible current-work status before starting a task phase.",
    );
    expect(result.message?.display).toBe(false);
  });

  it("hides current-work calls, lets other tools run, and clears after the agent settles", async () => {
    const extension = setup();

    expect(
      await extension.currentWorkHandler(toolCall("read"), extension.context),
    ).toBeUndefined();
    expect(extension.currentWorkTool.renderShell).toBe("self");
    expect(extension.currentWorkTool.renderCall().render(80)).toEqual([]);
    expect(extension.currentWorkTool.renderResult().render(80)).toEqual([]);

    await extension.currentWorkHandler(
      toolCall("set_current_work", { status: "Writing regression tests" }),
      extension.context,
    );
    await expect(
      extension.currentWorkTool.execute(
        "call-1",
        { status: "Writing regression tests" },
        undefined,
        undefined,
        extension.context,
      ),
    ).resolves.toMatchObject({
      details: { status: "Writing regression tests" },
    });
    expect(
      await extension.currentWorkHandler(toolCall("read"), extension.context),
    ).toBeUndefined();

    expect(extension.setStatus).toHaveBeenLastCalledWith(
      "current-work",
      "Writing regression tests",
    );
    expect(extension.setWorkingMessage).toHaveBeenLastCalledWith(
      "Writing regression tests... (0s)",
    );

    await extension.agentEndHandler({}, extension.context);

    expect(extension.setStatus).toHaveBeenLastCalledWith(
      "current-work",
      "Writing regression tests",
    );
    expect(extension.setWorkingMessage).toHaveBeenLastCalledWith();

    await extension.settledHandler({}, extension.context);

    expect(extension.setStatus).toHaveBeenLastCalledWith(
      "current-work",
      undefined,
    );
  });

  it("shows elapsed time with the current task phase", async () => {
    vi.useFakeTimers();
    try {
      const extension = setup("tui");

      await extension.agentStartHandler({}, extension.context);
      await extension.currentWorkHandler(
        toolCall("set_current_work", { status: "Writing regression tests" }),
        extension.context,
      );
      vi.advanceTimersByTime(2_000);

      expect(extension.setStatus).not.toHaveBeenCalled();
      expect(extension.setWorkingMessage).toHaveBeenLastCalledWith(
        "Writing regression tests... (2s)",
      );

      await extension.agentEndHandler({}, extension.context);
      expect(extension.setWorkingMessage).toHaveBeenLastCalledWith();
    } finally {
      vi.useRealTimers();
    }
  });
});
