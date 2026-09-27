import type {
  BrowserScriptResult,
  IBrowserScriptRunner,
  ITaskBrowserSettings,
  ITaskBrowserTabs,
} from "@posthog/platform/task-browser";
import { TASK_BROWSER_MCP_SERVER } from "@posthog/shared/constants";
import { describe, expect, it, vi } from "vitest";
import type { PermissionDecision, PermissionRequest } from "./schemas";
import { TaskBrowserEvent } from "./schemas";
import { siteDecisionResult, TaskBrowserService } from "./taskBrowserService";

type ScriptCall = (method: string, args: unknown[]) => Promise<unknown>;

function setup(options: { fullCdpAccess?: boolean; form?: unknown } = {}) {
  const urls = new Map<number, string>();
  const tabs = {
    isWebview: () => true,
    isDestroyed: (id: number) => !urls.has(id),
    onConsole: vi.fn(),
    onDestroyed: vi.fn(),
    url: (id: number) => urls.get(id) ?? "",
    title: () => "Page",
    waitForLoad: async () => undefined,
    runScript: async <T>(_id: number, code: string) =>
      (code.includes("document.activeElement")
        ? (options.form ?? null)
        : "result") as T,
    zoom: () => 1,
    capture: async () => null,
    click: vi.fn(),
    pressKey: vi.fn(),
    insertText: vi.fn(),
    goBack: vi.fn(),
    goForward: vi.fn(),
    reload: vi.fn(),
    load: vi.fn(async (id: number, url: string) => {
      urls.set(id, url);
    }),
    sendCdp: vi.fn(async () => ({})),
    clearBrowsingData: async () => undefined,
  } satisfies ITaskBrowserTabs;
  let sites: Record<string, "allow" | "block"> = {};
  let fullCdpAccess = options.fullCdpAccess ?? false;
  const settings: ITaskBrowserSettings = {
    sites: () => sites,
    setSites: (next) => {
      sites = next;
    },
    fullCdpAccess: () => fullCdpAccess,
    setFullCdpAccess: (enabled) => {
      fullCdpAccess = enabled;
    },
  };
  let resolveRun: (result: BrowserScriptResult) => void = () => undefined;
  let scriptCall: ScriptCall = async () => undefined;
  const runner: IBrowserScriptRunner = {
    start: (_code, call) => {
      scriptCall = call;
      return {
        done: new Promise((resolve) => {
          resolveRun = resolve;
        }),
        stop: vi.fn(),
      };
    },
  };
  const service = new TaskBrowserService(tabs, settings, runner);
  const prompts: PermissionRequest[] = [];
  const answers: PermissionDecision[] = [];
  service.on(TaskBrowserEvent.PermissionRequest, (request) => {
    prompts.push(request);
    const answer = answers.shift();
    if (answer) {
      queueMicrotask(() =>
        service.respondToPermission(request.requestId, answer),
      );
    }
  });
  const openTab = (
    taskId: string,
    browserId: string,
    id: number,
    url: string,
  ) => {
    urls.set(id, url);
    service.register({ browserId, taskId, kind: "browser", webContentsId: id });
  };
  const startRun = (taskId: string) => {
    const result = service.runCode(taskId, "code");
    return {
      call: (method: string, ...args: unknown[]) => scriptCall(method, args),
      finish: async () => {
        resolveRun({ ok: true, output: "" });
        return result;
      },
    };
  };
  return {
    service,
    tabs,
    prompts,
    answers,
    openTab,
    startRun,
    sites: () => sites,
  };
}

describe("TaskBrowserService", () => {
  it.each([
    ["allow-always", "allow", true],
    ["allow-task", null, true],
    ["allow-once", null, true],
    ["deny", null, false],
    ["block", "block", false],
  ] as const)(
    "maps the %s answer to a saved policy and an outcome",
    (decision, save, allow) => {
      expect(siteDecisionResult(decision)).toEqual({ save, allow });
    },
  );

  it("never lets one task use or reopen another task's tab", async () => {
    const { openTab, startRun, answers } = setup();
    openTab("task-1", "tab-a", 1, "https://example.com/");
    answers.push("allow-task");
    const run = startRun("task-2");

    await expect(run.call("snapshot", "tab-a")).rejects.toThrow(
      "No open tab tab-a in this task.",
    );
    await expect(run.call("tabs")).resolves.toEqual([]);
    await run.finish();
  });

  it("hides the page of a tab the task may not use, and closes only tabs the agent opened", async () => {
    const { openTab, startRun } = setup();
    openTab("task-1", "tab-a", 1, "https://example.com/inbox?thread=secret");
    const run = startRun("task-1");

    await expect(run.call("tabs")).resolves.toEqual([
      { id: "tab-a", kind: "browser", url: "https://example.com", title: "" },
    ]);
    await expect(run.call("close", "tab-a")).rejects.toThrow(
      "The agent can close only tabs it opened.",
    );
    await run.finish();
  });

  it("keeps a user tab reachable after its frame unmounts, until the user closes it", async () => {
    const { service, openTab, startRun, answers } = setup();
    openTab("task-1", "tab-u", 1, "https://example.com/");
    service.unregister("tab-u", 1, "https://example.com/deep/page");
    service.on(TaskBrowserEvent.OpenRequest, ({ browserId, url }) =>
      openTab("task-1", browserId, 2, url),
    );
    answers.push("allow-task");
    const run = startRun("task-1");

    await expect(run.call("tabs")).resolves.toEqual([
      { id: "tab-u", kind: "browser", url: "https://example.com", title: "" },
    ]);
    await expect(run.call("snapshot", "tab-u")).resolves.toBe("result");

    service.unregister("tab-u", 2, "https://example.com/deep/page");
    service.forgetTab("tab-u");
    await expect(run.call("snapshot", "tab-u")).rejects.toThrow(
      "No open tab tab-u in this task.",
    );
    await run.finish();
  });

  it("asks before the agent submits a filled form with Enter", async () => {
    const { openTab, startRun, answers, prompts, tabs } = setup({
      form: { password: false, payment: false, filled: true },
    });
    openTab("task-1", "tab-a", 1, "https://example.com/");
    answers.push("allow-task", "deny");
    const run = startRun("task-1");

    await expect(run.call("press", "tab-a", "Enter")).rejects.toThrow(
      "press Enter to submit the form",
    );
    expect(prompts.map((prompt) => prompt.kind)).toEqual([
      "site",
      "sensitive-action",
    ]);
    expect(tabs.pressKey).not.toHaveBeenCalled();
    await run.finish();
  });

  it("runs page scripts only with Full DevTools access and a per-site approval", async () => {
    const off = setup();
    off.openTab("task-1", "tab-a", 1, "https://example.com/");
    off.answers.push("allow-task");
    const refused = off.startRun("task-1");
    await expect(refused.call("evaluate", "tab-a", "1")).rejects.toThrow(
      "Full DevTools access",
    );
    await refused.finish();

    const on = setup({ fullCdpAccess: true });
    on.openTab("task-1", "tab-a", 1, "https://example.com/");
    on.openTab("task-1", "tab-b", 2, "https://other.example/");
    on.answers.push("allow-task", "allow-once", "allow-task", "allow-once");
    const run = on.startRun("task-1");
    await run.call("evaluate", "tab-a", "1");
    await run.call("evaluate", "tab-a", "2");
    await run.call("evaluate", "tab-b", "3");
    expect(on.prompts.map((prompt) => [prompt.kind, prompt.origin])).toEqual([
      ["site", "https://example.com"],
      ["full-cdp", "https://example.com"],
      ["site", "https://other.example"],
      ["full-cdp", "https://other.example"],
    ]);
    await run.finish();
  });

  it("blocks page navigation to an unapproved site only while the agent runs", async () => {
    const { service, openTab, startRun, answers } = setup();
    openTab("task-1", "tab-a", 1, "https://example.com/");
    expect(service.mayNavigate(1, "https://elsewhere.example/")).toBe(true);

    answers.push("allow-task");
    const run = startRun("task-1");
    await run.call("snapshot", "tab-a");
    expect(service.mayNavigate(1, "https://example.com/next")).toBe(true);
    expect(service.mayNavigate(1, "https://elsewhere.example/")).toBe(false);
    expect(service.openFromPage(1, "https://elsewhere.example/")).toBe(
      "blocked",
    );
    await run.finish();

    expect(service.mayNavigate(1, "https://elsewhere.example/")).toBe(true);
  });

  it("denies a pending prompt when the run ends", async () => {
    const { service, openTab, startRun, prompts } = setup();
    openTab("task-1", "tab-a", 1, "https://example.com/");
    const settled = vi.fn();
    service.on(TaskBrowserEvent.PermissionSettled, settled);
    const run = startRun("task-1");
    const call = run.call("snapshot", "tab-a");
    await vi.waitFor(() => expect(prompts).toHaveLength(1));

    await run.finish();

    await expect(call).rejects.toThrow("did not allow");
    expect(settled).toHaveBeenCalledWith({ requestId: prompts[0].requestId });
  });

  it("sends browser relay calls to the browser and other servers to the fallback", async () => {
    const { service } = setup();
    const fallback = { execute: vi.fn(async () => ({ payload: {} })) };
    const executor = service.relayExecutor(fallback);
    const payload = { jsonrpc: "2.0", id: 1, method: "tools/list" };

    await executor.execute("run-1", "slack", payload, "task-1");
    expect(fallback.execute).toHaveBeenCalledWith(
      "run-1",
      "slack",
      payload,
      "task-1",
    );

    const browser = await executor.execute(
      "run-1",
      TASK_BROWSER_MCP_SERVER,
      payload,
      "task-1",
    );
    expect(browser.payload?.result).toBeDefined();
    expect(fallback.execute).toHaveBeenCalledOnce();
    await expect(
      executor.execute("run-1", TASK_BROWSER_MCP_SERVER, payload),
    ).resolves.toEqual({
      error: { code: -32000, message: "Unknown task for the browser." },
    });
  });
});
