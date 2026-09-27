import type { McpRelayExecutor } from "@posthog/core/cloud-task/identifiers";
import {
  BROWSER_SCRIPT_RUNNER,
  type IBrowserScriptRunner,
  type ITaskBrowserSettings,
  type ITaskBrowserTabs,
  TASK_BROWSER_SETTINGS,
  TASK_BROWSER_TABS,
  type TaskBrowserImage,
  type TaskBrowserRect,
} from "@posthog/platform/task-browser";
import { TypedEventEmitter } from "@posthog/shared";
import { TASK_BROWSER_MCP_SERVER } from "@posthog/shared/constants";
import { inject, injectable } from "inversify";
import { isTabScopedCdpMethod } from "./cdp-policy";
import { BrowserMcpHandler, type BrowserRunResult } from "./mcp-handler";
import {
  evaluateScript,
  findTextScript,
  focusedFormScript,
  focusScript,
  rectScript,
  sensitivityScript,
  snapshotScript,
} from "./page-scripts";
import { PausableTimeout } from "./pausable-timeout";
import {
  type BrowserSettings,
  type BrowserTabKind,
  type PermissionDecision,
  type PermissionKind,
  type RegisterTabInput,
  type SitePolicy,
  TaskBrowserEvent,
  type TaskBrowserEvents,
} from "./schemas";
import { originOf, SitePolicyStore } from "./site-policy";

const REGISTRATION_TIMEOUT_MS = 15_000;
const PERMISSION_TIMEOUT_MS = 120_000;
const RUN_TIMEOUT_MS = 90_000;
const MAX_CALLS_PER_RUN = 300;
const MAX_OUTPUT_CHARS = 60_000;
const MAX_LOG_ENTRIES = 200;
const SNAPSHOT_MAX_CHARS = 24_000;
const MAX_WAIT_MS = 20_000;

type LogEntry = { at: number; text: string };

type BrowserTab = {
  browserId: string;
  taskId: string;
  kind: BrowserTabKind;
  tabId: number;
  console: LogEntry[];
  network: LogEntry[];
};

type CallContext = {
  taskId: string;
  images: TaskBrowserImage[];
  timeout?: PausableTimeout;
};

type PendingPermission = {
  context: CallContext;
  resolve: (decision: PermissionDecision) => void;
  timer: ReturnType<typeof setTimeout>;
};

type Sensitivity = {
  typesPassword: boolean;
  password: boolean;
  payment: boolean;
  submitsData: boolean;
  destructive: boolean;
  label: string;
};

export class BrowserToolError extends Error {}

export function siteDecisionResult(decision: PermissionDecision): {
  save: SitePolicy | null;
  allow: boolean;
} {
  switch (decision) {
    case "allow-always":
      return { save: "allow", allow: true };
    case "allow-task":
    case "allow-once":
      return { save: null, allow: true };
    case "block":
      return { save: "block", allow: false };
    case "deny":
      return { save: null, allow: false };
  }
}

function pushLog(entries: LogEntry[], text: string): void {
  entries.push({ at: Date.now(), text });
  if (entries.length > MAX_LOG_ENTRIES) entries.shift();
}

function stringArg(value: unknown, name: string): string {
  if (typeof value !== "string" || !value) {
    throw new BrowserToolError(`${name} must be a non-empty string.`);
  }
  return value;
}

@injectable()
export class TaskBrowserService extends TypedEventEmitter<TaskBrowserEvents> {
  readonly mcp: BrowserMcpHandler;
  private readonly tabs = new Map<string, BrowserTab>();
  private readonly waiters = new Map<string, Array<() => void>>();
  private readonly pending = new Map<string, PendingPermission>();
  private readonly developerApprovals = new Set<string>();
  private readonly reopenable = new Map<
    string,
    { taskId: string; url: string }
  >();
  private readonly activeRuns = new Map<string, number>();
  private readonly sites: SitePolicyStore;

  constructor(
    @inject(TASK_BROWSER_TABS) private readonly host: ITaskBrowserTabs,
    @inject(TASK_BROWSER_SETTINGS)
    private readonly settingsStore: ITaskBrowserSettings,
    @inject(BROWSER_SCRIPT_RUNNER)
    private readonly runner: IBrowserScriptRunner,
  ) {
    super();
    this.sites = new SitePolicyStore(
      () => this.settingsStore.sites(),
      (sites) => this.settingsStore.setSites(sites),
    );
    this.mcp = new BrowserMcpHandler((taskId, code) =>
      this.runCode(taskId, code),
    );
  }

  register(input: RegisterTabInput): void {
    if (!this.host.isWebview(input.webContentsId)) return;
    const tab: BrowserTab = {
      browserId: input.browserId,
      taskId: input.taskId,
      kind: input.kind,
      tabId: input.webContentsId,
      console: [],
      network: [],
    };
    this.tabs.set(input.browserId, tab);
    this.host.onConsole(tab.tabId, (text) => pushLog(tab.console, text));
    this.host.onDestroyed(tab.tabId, () => {
      if (this.tabs.get(input.browserId)?.tabId === tab.tabId) {
        this.tabs.delete(input.browserId);
      }
    });
    for (const resolve of this.waiters.get(input.browserId) ?? []) resolve();
    this.waiters.delete(input.browserId);
  }

  unregister(browserId: string, webContentsId: number): void {
    if (this.tabs.get(browserId)?.tabId === webContentsId) {
      this.tabs.delete(browserId);
    }
  }

  recordNetwork(webContentsId: number | undefined, text: string): void {
    if (webContentsId === undefined) return;
    for (const tab of this.tabs.values()) {
      if (tab.tabId === webContentsId) pushLog(tab.network, text);
    }
  }

  mayNavigate(webContentsId: number, url: string): boolean {
    const tab = this.tabForWebContents(webContentsId);
    if (!tab || tab.kind !== "browser" || !this.activeRuns.get(tab.taskId)) {
      return true;
    }
    const origin = originOf(url);
    return !origin || this.sites.access(tab.taskId, origin) === "allowed";
  }

  openFromPage(
    webContentsId: number,
    url: string,
  ): "opened" | "blocked" | "untracked" {
    const tab = this.tabForWebContents(webContentsId);
    if (!tab) return "untracked";
    if (!this.mayNavigate(webContentsId, url)) return "blocked";
    this.requestOpen(tab.taskId, url);
    return "opened";
  }

  forgetTask(taskId: string): void {
    this.sites.forgetTask(taskId);
    for (const key of this.developerApprovals) {
      if (key.startsWith(`${taskId}|`)) this.developerApprovals.delete(key);
    }
  }

  respondToPermission(requestId: string, decision: PermissionDecision): void {
    this.settlePrompt(requestId, decision);
  }

  settings(): BrowserSettings {
    return {
      sites: this.sites.list(),
      fullCdpAccess: this.settingsStore.fullCdpAccess(),
    };
  }

  setSitePolicy(origin: string, policy: SitePolicy | null): void {
    this.sites.set(origin, policy);
  }

  setFullCdpAccess(enabled: boolean): void {
    this.settingsStore.setFullCdpAccess(enabled);
    if (!enabled) this.developerApprovals.clear();
  }

  clearBrowsingData(): Promise<void> {
    return this.host.clearBrowsingData();
  }

  relayExecutor(fallback: McpRelayExecutor): McpRelayExecutor {
    return {
      execute: async (runId, server, payload, taskId) => {
        if (server !== TASK_BROWSER_MCP_SERVER) {
          return fallback.execute(runId, server, payload, taskId);
        }
        if (!taskId) {
          return {
            error: { code: -32000, message: "Unknown task for the browser." },
          };
        }
        const response = await this.mcp.handle(taskId, payload);
        return response ? { payload: response } : {};
      },
      closeRun: (runId) => fallback.closeRun?.(runId) ?? Promise.resolve(),
    };
  }

  async runCode(taskId: string, code: string): Promise<BrowserRunResult> {
    const context: CallContext = { taskId, images: [] };
    let calls = 0;
    this.activeRuns.set(taskId, (this.activeRuns.get(taskId) ?? 0) + 1);
    const run = this.runner.start(code, async (method, args) => {
      calls += 1;
      if (calls > MAX_CALLS_PER_RUN) {
        throw new BrowserToolError(
          `More than ${MAX_CALLS_PER_RUN} browser calls in one run.`,
        );
      }
      return this.call(context, method, args);
    });
    const timedOut = new Promise<{ ok: boolean; output: string }>((resolve) => {
      context.timeout = new PausableTimeout(RUN_TIMEOUT_MS, () =>
        resolve({
          ok: false,
          output: `Error: the code ran longer than ${RUN_TIMEOUT_MS / 1000} s.`,
        }),
      );
    });
    try {
      const result = await Promise.race([run.done, timedOut]);
      const output =
        result.output.length > MAX_OUTPUT_CHARS
          ? `${result.output.slice(0, MAX_OUTPUT_CHARS)}\n… output truncated`
          : result.output;
      return { ok: result.ok, output, images: context.images };
    } finally {
      context.timeout?.stop();
      run.stop();
      this.cancelPrompts(context);
      const active = (this.activeRuns.get(taskId) ?? 1) - 1;
      if (active > 0) this.activeRuns.set(taskId, active);
      else this.activeRuns.delete(taskId);
    }
  }

  requestOpen(
    taskId: string,
    url: string,
    browserId: string = crypto.randomUUID(),
  ): string {
    this.reopenable.set(browserId, { taskId, url });
    this.emit(TaskBrowserEvent.OpenRequest, { taskId, browserId, url });
    return browserId;
  }

  async call(
    context: CallContext,
    method: string,
    args: unknown[],
  ): Promise<unknown> {
    switch (method) {
      case "tabs":
        return this.listTabs(context.taskId);
      case "open":
        return this.open(context, stringArg(args[0], "url"));
      case "close":
        return this.close(context.taskId, stringArg(args[0], "tab"));
      case "snapshot":
        return this.withTab(context, args[0], (tab) =>
          this.run<string>(tab, snapshotScript(SNAPSHOT_MAX_CHARS)),
        );
      case "find":
        return this.withTab(context, args[0], (tab) =>
          this.run<string | null>(
            tab,
            findTextScript(stringArg(args[1], "text")),
          ),
        );
      case "screenshot":
        return this.withTab(context, args[0], (tab) =>
          this.screenshot(context, tab, args[1]),
        );
      case "click":
        return this.withTab(context, args[0], (tab) =>
          this.click(context, tab, stringArg(args[1], "ref")),
        );
      case "type":
        return this.withTab(context, args[0], (tab) =>
          this.type(
            context,
            tab,
            stringArg(args[1], "ref"),
            typeof args[2] === "string" ? args[2] : "",
            args[3] === true,
          ),
        );
      case "press":
        return this.withTab(context, args[0], (tab) =>
          this.press(context, tab, stringArg(args[1], "key")),
        );
      case "scroll":
        return this.withTab(context, args[0], (tab) =>
          this.scroll(tab, Number(args[1]) || 0),
        );
      case "navigate":
        return this.withTab(context, args[0], (tab) =>
          this.navigate(context, tab, stringArg(args[1], "target")),
        );
      case "waitFor":
        return this.withTab(context, args[0], (tab) =>
          this.waitFor(tab, stringArg(args[1], "text"), Number(args[2])),
        );
      case "console":
        return this.withTab(context, args[0], async (tab) =>
          this.logsSince(tab.console, Number(args[1]) || 0),
        );
      case "network":
        return this.withTab(context, args[0], async (tab) =>
          this.logsSince(tab.network, Number(args[1]) || 0),
        );
      case "evaluate":
        return this.withTab(context, args[0], async (tab) => {
          await this.ensureDeveloperAccess(context, tab, "run scripts on");
          return this.run(tab, evaluateScript(stringArg(args[1], "source")));
        });
      case "cdp":
        return this.withTab(context, args[0], (tab) =>
          this.cdp(context, tab, stringArg(args[1], "method"), args[2]),
        );
      default:
        throw new BrowserToolError(`Unknown browser method: ${method}`);
    }
  }

  private tabForWebContents(webContentsId: number): BrowserTab | null {
    for (const tab of this.tabs.values()) {
      if (tab.tabId === webContentsId) return tab;
    }
    return null;
  }

  private listTabs(taskId: string) {
    return [...this.tabs.values()]
      .filter(
        (tab) => tab.taskId === taskId && !this.host.isDestroyed(tab.tabId),
      )
      .map((tab) => ({
        id: tab.browserId,
        kind: tab.kind,
        url: this.host.url(tab.tabId),
        title: this.host.title(tab.tabId),
      }));
  }

  private async open(context: CallContext, url: string) {
    const origin = originOf(url);
    if (!origin) throw new BrowserToolError("Only http and https URLs open.");
    await this.ensureSiteAccess(context, origin);
    const browserId = this.requestOpen(context.taskId, url);
    const tab = await this.awaitTab(browserId);
    await this.host.waitForLoad(tab.tabId);
    return {
      id: tab.browserId,
      url: this.host.url(tab.tabId),
      title: this.host.title(tab.tabId),
    };
  }

  private async close(taskId: string, browserId: string) {
    const tab = this.tabs.get(browserId);
    if (!tab || tab.taskId !== taskId) {
      throw new BrowserToolError(`No open tab ${browserId} in this task.`);
    }
    this.tabs.delete(browserId);
    this.reopenable.delete(browserId);
    this.emit(TaskBrowserEvent.CloseRequest, { taskId, browserId });
    return true;
  }

  private async withTab<T>(
    context: CallContext,
    tabArg: unknown,
    action: (tab: BrowserTab) => Promise<T>,
  ): Promise<T> {
    const browserId = stringArg(tabArg, "tab");
    let tab = this.tabs.get(browserId);
    if (tab && tab.taskId !== context.taskId) {
      throw new BrowserToolError(`No open tab ${browserId} in this task.`);
    }
    if (!tab || this.host.isDestroyed(tab.tabId)) {
      const saved = this.reopenable.get(browserId);
      if (!saved || saved.taskId !== context.taskId) {
        throw new BrowserToolError(`No open tab ${browserId} in this task.`);
      }
      this.requestOpen(context.taskId, saved.url, browserId);
      tab = await this.awaitTab(browserId);
    }
    const origin = originOf(this.host.url(tab.tabId));
    if (origin) await this.ensureSiteAccess(context, origin);
    return action(tab);
  }

  private awaitTab(browserId: string): Promise<BrowserTab> {
    const existing = this.tabs.get(browserId);
    if (existing && !this.host.isDestroyed(existing.tabId)) {
      return Promise.resolve(existing);
    }
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        reject(
          new BrowserToolError(
            "The browser tab did not open. The task must be open in PostHog Desktop for the agent to use the browser.",
          ),
        );
      }, REGISTRATION_TIMEOUT_MS);
      const waiters = this.waiters.get(browserId) ?? [];
      waiters.push(() => {
        clearTimeout(timer);
        const tab = this.tabs.get(browserId);
        if (tab) resolve(tab);
      });
      this.waiters.set(browserId, waiters);
    });
  }

  private run<T>(tab: BrowserTab, code: string): Promise<T> {
    return this.host.runScript<T>(tab.tabId, code);
  }

  private async screenshot(
    context: CallContext,
    tab: BrowserTab,
    refArg: unknown,
  ): Promise<string> {
    let rect: TaskBrowserRect | undefined;
    if (typeof refArg === "string" && refArg) {
      const box = await this.run<{
        left: number;
        top: number;
        width: number;
        height: number;
      } | null>(tab, rectScript(refArg));
      if (!box) throw new BrowserToolError(`No element ${refArg} on the page.`);
      const zoom = this.host.zoom(tab.tabId);
      rect = {
        x: Math.max(0, Math.round(box.left * zoom)),
        y: Math.max(0, Math.round(box.top * zoom)),
        width: Math.max(1, Math.round(box.width * zoom)),
        height: Math.max(1, Math.round(box.height * zoom)),
      };
    }
    let image = await this.host.capture(tab.tabId, rect);
    if (!image && tab.kind === "browser") {
      this.requestOpen(tab.taskId, this.host.url(tab.tabId), tab.browserId);
      await new Promise((resolve) => setTimeout(resolve, 400));
      image = await this.host.capture(tab.tabId, rect);
    }
    if (!image) {
      throw new BrowserToolError(
        tab.kind === "browser"
          ? "The tab could not be captured. Try again."
          : "The preview is not on screen. Ask the user to open it, then try again.",
      );
    }
    context.images.push(image);
    return `screenshot ${context.images.length} attached`;
  }

  private async point(tab: BrowserTab, ref: string) {
    const box = await this.run<{ x: number; y: number } | null>(
      tab,
      rectScript(ref),
    );
    if (!box) throw new BrowserToolError(`No element ${ref} on the page.`);
    const zoom = this.host.zoom(tab.tabId);
    return { x: Math.round(box.x * zoom), y: Math.round(box.y * zoom) };
  }

  private async click(context: CallContext, tab: BrowserTab, ref: string) {
    const sensitivity = await this.run<Sensitivity | null>(
      tab,
      sensitivityScript(ref),
    );
    if (!sensitivity) {
      throw new BrowserToolError(`No element ${ref} on the page.`);
    }
    const origin = this.originOrPage(tab);
    if (
      sensitivity.payment ||
      sensitivity.submitsData ||
      sensitivity.destructive
    ) {
      await this.confirm(context, "sensitive-action", origin, [
        `click “${sensitivity.label || ref}”`,
        sensitivity.payment ? "on a form with payment fields" : null,
        sensitivity.submitsData
          ? "to submit the information typed into the form"
          : null,
      ]);
    } else if (sensitivity.password && sensitivity.label) {
      await this.confirm(context, "sign-in", origin, [
        `click “${sensitivity.label}” on a sign-in form`,
      ]);
    }
    const { x, y } = await this.point(tab, ref);
    this.host.click(tab.tabId, x, y);
    await this.settle(tab);
    return true;
  }

  private async type(
    context: CallContext,
    tab: BrowserTab,
    ref: string,
    text: string,
    clear: boolean,
  ) {
    const sensitivity = await this.run<Sensitivity | null>(
      tab,
      sensitivityScript(ref),
    );
    if (!sensitivity) {
      throw new BrowserToolError(`No element ${ref} on the page.`);
    }
    const origin = this.originOrPage(tab);
    if (sensitivity.typesPassword) {
      await this.confirm(context, "sign-in", origin, [
        "type into a password field",
      ]);
    } else if (sensitivity.payment) {
      await this.confirm(context, "sensitive-action", origin, [
        "type into a payment field",
      ]);
    }
    const focused = await this.run<boolean>(tab, focusScript(ref, clear));
    if (!focused)
      throw new BrowserToolError(`Element ${ref} cannot take text.`);
    this.host.insertText(tab.tabId, text, clear);
    return true;
  }

  private async press(context: CallContext, tab: BrowserTab, key: string) {
    if (key === "Enter") {
      const form = await this.run<{
        password: boolean;
        payment: boolean;
        filled: boolean;
      } | null>(tab, focusedFormScript());
      if (form && (form.password || form.payment || form.filled)) {
        await this.confirm(
          context,
          form.password ? "sign-in" : "sensitive-action",
          this.originOrPage(tab),
          ["press Enter to submit the form"],
        );
      }
    }
    this.host.pressKey(tab.tabId, key);
    await this.settle(tab);
    return true;
  }

  private async scroll(tab: BrowserTab, deltaY: number) {
    await this.run(
      tab,
      `(() => { window.scrollBy(0, ${Math.round(deltaY)}); return true; })()`,
    );
    return true;
  }

  private async navigate(
    context: CallContext,
    tab: BrowserTab,
    target: string,
  ) {
    if (target === "back") {
      this.host.goBack(tab.tabId);
    } else if (target === "forward") {
      this.host.goForward(tab.tabId);
    } else if (target === "reload") {
      this.host.reload(tab.tabId);
    } else {
      const current = this.host.url(tab.tabId);
      const next = new URL(target, current);
      const origin = originOf(next.toString());
      if (!origin) throw new BrowserToolError("Only http and https URLs open.");
      if (tab.kind === "preview" && origin !== originOf(current)) {
        throw new BrowserToolError(
          "A preview tab stays on its own site. Open other sites with browser.open.",
        );
      }
      await this.ensureSiteAccess(context, origin);
      await this.host.load(tab.tabId, next.toString());
    }
    await this.settle(tab);
    return { url: this.host.url(tab.tabId), title: this.host.title(tab.tabId) };
  }

  private async waitFor(tab: BrowserTab, text: string, timeoutArg: number) {
    const timeout = Math.min(
      Number.isFinite(timeoutArg) && timeoutArg > 0 ? timeoutArg : 5_000,
      MAX_WAIT_MS,
    );
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      const ref = await this.run<string | null>(tab, findTextScript(text));
      if (ref) return ref;
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    throw new BrowserToolError(
      `"${text}" did not appear within ${timeout} ms.`,
    );
  }

  private logsSince(entries: LogEntry[], since: number) {
    return entries
      .filter((entry) => entry.at > since)
      .map((entry) => ({ at: entry.at, text: entry.text }));
  }

  private async cdp(
    context: CallContext,
    tab: BrowserTab,
    method: string,
    params: unknown,
  ) {
    if (method.startsWith("Input.")) {
      throw new BrowserToolError(
        `${method} is not available. Use tab.click, tab.type and tab.press, which ask the user before sensitive actions.`,
      );
    }
    if (!isTabScopedCdpMethod(method)) {
      throw new BrowserToolError(
        `${method} is not available because it reaches beyond this site.`,
      );
    }
    await this.ensureDeveloperAccess(
      context,
      tab,
      "use the Chrome DevTools Protocol on",
    );
    if (method === "Page.navigate") {
      const target = (params as { url?: unknown } | null)?.url;
      const origin = typeof target === "string" ? originOf(target) : null;
      if (!origin) {
        throw new BrowserToolError("Page.navigate needs an http or https URL.");
      }
      await this.ensureSiteAccess(context, origin);
    }
    return this.host.sendCdp(
      tab.tabId,
      method,
      params && typeof params === "object" ? params : {},
    );
  }

  private async ensureDeveloperAccess(
    context: CallContext,
    tab: BrowserTab,
    action: string,
  ) {
    if (!this.settingsStore.fullCdpAccess()) {
      throw new BrowserToolError(
        "Scripts and DevTools access are off. The user can turn on Full DevTools access in Settings > Browser.",
      );
    }
    const origin = originOf(this.host.url(tab.tabId));
    if (!origin) {
      throw new BrowserToolError("This page is not an http or https page.");
    }
    const key = `${context.taskId}|${origin}`;
    if (this.developerApprovals.has(key)) return;
    await this.confirm(context, "full-cdp", origin, [`${action} this site`]);
    this.developerApprovals.add(key);
  }

  private originOrPage(tab: BrowserTab): string {
    return originOf(this.host.url(tab.tabId)) ?? "this page";
  }

  private async settle(tab: BrowserTab) {
    await new Promise((resolve) => setTimeout(resolve, 150));
    await this.host.waitForLoad(tab.tabId);
  }

  private async ensureSiteAccess(context: CallContext, origin: string) {
    const access = this.sites.access(context.taskId, origin);
    if (access === "allowed") return;
    if (access === "blocked") {
      throw new BrowserToolError(`The user blocked ${origin} for the agent.`);
    }
    const decision = await this.ask(context, "site", origin, `Use ${origin}`);
    const result = siteDecisionResult(decision);
    if (result.save) this.sites.set(origin, result.save);
    if (!result.allow) {
      throw new BrowserToolError(
        `The user did not allow the agent to use ${origin}.`,
      );
    }
    this.sites.approveForTask(context.taskId, origin);
  }

  private async confirm(
    context: CallContext,
    kind: PermissionKind,
    origin: string,
    parts: Array<string | null>,
  ) {
    const detail = parts.filter(Boolean).join(" ");
    const decision = await this.ask(context, kind, origin, detail);
    if (decision === "deny" || decision === "block") {
      throw new BrowserToolError(
        `The user did not allow this action: ${detail}.`,
      );
    }
  }

  private cancelPrompts(context: CallContext): void {
    for (const [requestId, pending] of this.pending) {
      if (pending.context === context) this.settlePrompt(requestId, "deny");
    }
  }

  private settlePrompt(requestId: string, decision: PermissionDecision) {
    const pending = this.pending.get(requestId);
    if (!pending) return;
    clearTimeout(pending.timer);
    this.pending.delete(requestId);
    pending.context.timeout?.unpause();
    this.emit(TaskBrowserEvent.PermissionSettled, { requestId });
    pending.resolve(decision);
  }

  private ask(
    context: CallContext,
    kind: PermissionKind,
    origin: string,
    detail: string,
  ): Promise<PermissionDecision> {
    const requestId = crypto.randomUUID();
    return new Promise((resolve) => {
      const timer = setTimeout(
        () => this.settlePrompt(requestId, "deny"),
        PERMISSION_TIMEOUT_MS,
      );
      this.pending.set(requestId, { context, resolve, timer });
      context.timeout?.pause();
      this.emit(TaskBrowserEvent.PermissionRequest, {
        requestId,
        taskId: context.taskId,
        kind,
        origin,
        detail,
      });
    });
  }
}
