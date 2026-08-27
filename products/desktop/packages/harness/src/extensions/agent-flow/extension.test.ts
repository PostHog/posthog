import {
  type AgentFlowDefinition,
  type AgentFlowRole,
  buildAgentFlowRunCommand,
} from "@posthog/shared";
import { describe, expect, it, vi } from "vitest";
import { createAgentFlowExtension, extractHandoff } from "./extension";
import { tryRouteFlowInput } from "./flow-input";
import type { StepSessionResult } from "./step-session";

type CommandHandler = (args: string, ctx: unknown) => Promise<void>;
type InputHandler = (
  event: { text: string },
  ctx: unknown,
) => { action: string } | undefined;

interface SentMessage {
  content: string;
  details?: {
    status?: string;
    stepIndex?: number;
    event?: string;
    approvalId?: string;
  };
}

function flowDefinition(
  overrides: Partial<{ approvalAfter: boolean }> = {},
): AgentFlowDefinition {
  const step = (name: string, role: AgentFlowRole, index: number) => ({
    id: `step-${index}`,
    name,
    role,
    model: { provider: "posthog" as const, id: "test-model", name: "Test" },
    effort: "medium" as const,
    approvalAfter: index === 0 && !!overrides.approvalAfter,
  });
  return {
    id: "flow-1",
    name: "Plan and build",
    steps: [step("Plan", "planner", 0), step("Build", "executor", 1)],
  };
}

function runResult(text: string, failed = false): StepSessionResult {
  return {
    output: text,
    failed,
    ...(failed ? { errorMessage: text } : {}),
  };
}

function harness(
  runStepResult: (options: { task: string }) => Promise<StepSessionResult>,
  revise?: (feedback: string) => Promise<StepSessionResult>,
  flowSkills: Array<{ flow: AgentFlowDefinition; dirName: string }> = [],
) {
  const runStep = async (options: { task: string }) => ({
    result: await runStepResult(options),
    revise: revise ?? (async () => runResult("<handoff>revised</handoff>")),
    dispose: () => {},
  });
  const sentMessages: SentMessage[] = [];
  const commands = new Map<string, CommandHandler>();
  type RegisteredTool = {
    name: string;
    execute: (
      id: string,
      params: { name: string; task: string },
      signal: undefined,
      onUpdate: undefined,
      ctx: unknown,
    ) => Promise<{ content: Array<{ type: string; text: string }> }>;
  };
  const tools = new Map<string, RegisteredTool>();
  const inputHandlers: InputHandler[] = [];
  const notifications: string[] = [];
  const confirm = vi.fn(async () => true);

  const pi = {
    on: (event: string, handler: unknown) => {
      if (event === "input") inputHandlers.push(handler as InputHandler);
    },
    registerCommand: (name: string, options: { handler: CommandHandler }) => {
      commands.set(name, options.handler);
    },
    registerTool: (tool: RegisteredTool) => {
      tools.set(tool.name, tool);
    },
    sendMessage: (message: SentMessage) => {
      sentMessages.push(message);
    },
  };
  const ctx = {
    hasUI: true,
    ui: {
      notify: (message: string) => {
        notifications.push(message);
      },
      confirm,
    },
  };

  createAgentFlowExtension({
    runStep: runStep as never,
    findFlow: (query: string) =>
      flowSkills.find(
        (skill) =>
          skill.dirName === query.toLowerCase() ||
          skill.flow.name.toLowerCase() === query.toLowerCase(),
      ) ?? null,
    listFlows: () => flowSkills,
  })(pi as never);

  const run = (
    prompt = "Make the game theme green",
    flow = flowDefinition(),
  ) => {
    const command = buildAgentFlowRunCommand(flow, prompt);
    const args = command.replace("/agent-flow-run ", "");
    return commands.get("agent-flow-run")?.(args, ctx) as Promise<void>;
  };

  const respond = (args: string) =>
    commands.get("agent-flow-respond")?.(args, ctx) as Promise<void>;

  const runTool = (name: string, task = "Make the game theme green") =>
    tools
      .get("run_agent_flow")
      ?.execute("t1", { name, task }, undefined, undefined, { cwd: "/x" });

  return {
    run,
    respond,
    runTool,
    sentMessages,
    inputHandlers,
    notifications,
    confirm,
    lastStatus: () => sentMessages[sentMessages.length - 1]?.details?.status,
    lastApprovalId: () =>
      [...sentMessages]
        .reverse()
        .find((message) => message.details?.event === "approval_requested")
        ?.details?.approvalId,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

describe("createAgentFlowExtension", () => {
  it("returns from the command handler before the flow finishes", async () => {
    const firstStep = deferred<StepSessionResult>();
    const h = harness(() => firstStep.promise);

    await h.run();

    expect(h.lastStatus()).toBe("running");

    firstStep.resolve(runResult("<handoff>plan</handoff>"));
    await vi.waitFor(() => expect(h.lastStatus()).toBe("completed"));
  });

  it("quotes the prompt without the channel context block", async () => {
    const h = harness(() => Promise.resolve(runResult("<handoff>x</handoff>")));

    await h.run(
      'Make it green\n\n<channel_context channel="personal">internal routing text</channel_context>',
    );
    await vi.waitFor(() => expect(h.lastStatus()).toBe("completed"));

    const start = h.sentMessages[0];
    expect(start.content).toContain("> Make it green");
    expect(start.content).not.toContain("channel_context");
  });

  it("passes the prior step's handoff into the next step's task", async () => {
    const tasks: string[] = [];
    const h = harness((options) => {
      tasks.push(options.task);
      return Promise.resolve(
        runResult("preamble\n<handoff>use file a.ts</handoff>"),
      );
    });

    await h.run();
    await vi.waitFor(() => expect(h.lastStatus()).toBe("completed"));

    expect(tasks[1]).toContain("Handoff from the prior step:\nuse file a.ts");
    expect(tasks[1]).not.toContain("preamble");
  });

  it("reports a failed step with a terminal failed status", async () => {
    const h = harness(() => Promise.resolve(runResult("boom", true)));

    await h.run();
    await vi.waitFor(() => expect(h.lastStatus()).toBe("failed"));

    const failure = h.sentMessages[h.sentMessages.length - 1];
    expect(failure.content).toContain("Plan failed");
  });

  it("steers the running step directly when one is active", async () => {
    const firstStep = deferred<StepSessionResult>();
    const steered: string[] = [];
    const h = harness((options) => {
      const withHooks = options as {
        onSteerAvailable?: (steer: (text: string) => void) => void;
      };
      withHooks.onSteerAvailable?.((text) => steered.push(text));
      return firstStep.promise;
    });

    await h.run();
    const result = h.inputHandlers[0]?.(
      { text: "focus on the css" },
      undefined,
    );

    expect(result).toEqual({ action: "handled" });
    expect(steered).toEqual(["focus on the css"]);
    const ack = h.sentMessages[h.sentMessages.length - 1];
    expect(ack.content).toContain("Sent to the running step");

    firstStep.resolve(runResult("<handoff>x</handoff>"));
    await vi.waitFor(() => expect(h.lastStatus()).not.toBe("running"));
  });

  it("queues user input during a flow into the next step's task", async () => {
    const firstStep = deferred<StepSessionResult>();
    const tasks: string[] = [];
    let calls = 0;
    const h = harness((options) => {
      tasks.push(options.task);
      calls += 1;
      return calls === 1
        ? firstStep.promise
        : Promise.resolve(runResult("<handoff>done</handoff>"));
    });

    await h.run();
    const result = h.inputHandlers[0]?.(
      { text: "prefer dark green" },
      undefined,
    );

    expect(result).toEqual({ action: "handled" });

    firstStep.resolve(runResult("<handoff>plan</handoff>"));
    await vi.waitFor(() => expect(h.lastStatus()).toBe("completed"));
    expect(tasks[1]).toContain("prefer dark green");
  });

  it("routes steer and follow-up through the flow-input router while running", async () => {
    const firstStep = deferred<StepSessionResult>();
    const tasks: string[] = [];
    let calls = 0;
    const h = harness((options) => {
      tasks.push(options.task);
      calls += 1;
      return calls === 1
        ? firstStep.promise
        : Promise.resolve(runResult("<handoff>done</handoff>"));
    });

    expect(tryRouteFlowInput("before flow", "steer")).toBe(false);
    await h.run();
    expect(tryRouteFlowInput("queued note", "followUp")).toBe(true);
    expect(tryRouteFlowInput("/agent-flow-run x", "steer")).toBe(false);

    firstStep.resolve(runResult("<handoff>plan</handoff>"));
    await vi.waitFor(() => expect(h.lastStatus()).toBe("completed"));
    expect(tasks[1]).toContain("queued note");
    expect(tryRouteFlowInput("after flow", "steer")).toBe(false);
  });

  it("lets input through when no flow is running", () => {
    const h = harness(() => Promise.resolve(runResult("unused")));

    expect(h.inputHandlers[0]?.({ text: "hello" }, undefined)).toBeUndefined();
  });

  it("refuses a second flow while one is running", async () => {
    const firstStep = deferred<StepSessionResult>();
    const h = harness(() => firstStep.promise);

    await h.run();
    await h.run();

    expect(h.notifications[0]).toContain("already running");
    firstStep.resolve(runResult("<handoff>plan</handoff>"));
    await vi.waitFor(() => expect(h.lastStatus()).toBe("completed"));
  });

  it("starts a saved flow from the run_agent_flow tool and refuses overlaps", async () => {
    const firstStep = deferred<StepSessionResult>();
    let calls = 0;
    const h = harness(
      () => {
        calls += 1;
        return calls === 1
          ? firstStep.promise
          : Promise.resolve(runResult("<handoff>done</handoff>"));
      },
      undefined,
      [{ flow: flowDefinition(), dirName: "plan-and-build" }],
    );

    const missing = await h.runTool("nope");
    expect(missing?.content[0]?.text).toContain("No saved flow");

    const started = await h.runTool("plan-and-build");
    expect(started?.content[0]?.text).toContain("Started");
    expect(h.sentMessages[0]?.details?.status).toBe("running");

    const overlap = await h.runTool("plan-and-build");
    expect(overlap?.content[0]?.text).toContain("already running");

    firstStep.resolve(runResult("<handoff>plan</handoff>"));
    await vi.waitFor(() => expect(h.lastStatus()).toBe("completed"));
  });

  it("revises the handoff with feedback and continues after approval", async () => {
    const reviseCalls: string[] = [];
    const tasks: string[] = [];
    const h = harness(
      (options) => {
        tasks.push(options.task);
        return Promise.resolve(runResult("<handoff>plan v1</handoff>"));
      },
      async (feedback) => {
        reviseCalls.push(feedback);
        return runResult("<handoff>plan v2</handoff>");
      },
    );

    await h.run("task", flowDefinition({ approvalAfter: true }));
    await vi.waitFor(() => expect(h.lastApprovalId()).toBeDefined());
    const firstApproval = h.lastApprovalId() as string;

    await h.respond(
      `${encodeURIComponent(firstApproval)} reject cover the edge cases`,
    );
    await vi.waitFor(() => expect(h.lastApprovalId()).not.toBe(firstApproval));
    expect(reviseCalls[0]).toContain("cover the edge cases");

    await h.respond(
      `${encodeURIComponent(h.lastApprovalId() as string)} approve`,
    );
    await vi.waitFor(() => expect(h.lastStatus()).toBe("completed"));
    expect(tasks[1]).toContain("plan v2");
  });
});

describe("extractHandoff", () => {
  it.each([
    ["<handoff>the plan</handoff>", "the plan"],
    ["intro\n<handoff>first</handoff>\n<handoff>second</handoff>", "second"],
    ["no tags at all", "no tags at all"],
    ["<handoff>   </handoff> trailing", "<handoff>   </handoff> trailing"],
  ])("extracts the handoff from %j", (output, expected) => {
    expect(extractHandoff(output)).toBe(expected);
  });
});
