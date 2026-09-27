import { randomUUID } from "node:crypto";
import { TypedEventEmitter } from "@posthog/shared";
import { session, type WebContents, webContents } from "electron";
import { injectable } from "inversify";
import { TASK_BROWSER_PARTITION } from "../../../shared/constants";
import { settingsStore } from "../../services/settingsStore";
import { isTabScopedCdpMethod } from "./cdp-policy";
import {
  evaluateScript,
  findTextScript,
  focusScript,
  PAGE_WORLD_ID,
  rectScript,
  sensitivityScript,
  snapshotScript,
} from "./page-scripts";
import {
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
const CAPTURE_TIMEOUT_MS = 2_000;

const MAX_LOG_ENTRIES = 200;
const SNAPSHOT_MAX_CHARS = 24_000;
const SCREENSHOT_MAX_WIDTH = 1_280;
const SCREENSHOT_QUALITY = 80;
const MAX_WAIT_MS = 20_000;

type LogEntry = { at: number; text: string };

type BrowserTab = {
  browserId: string;
  taskId: string;
  kind: BrowserTabKind;
  contents: WebContents;
  console: LogEntry[];
  network: LogEntry[];
};

export type BrowserImage = { data: string; mimeType: "image/jpeg" };

export type BrowserCallContext = {
  taskId: string;
  images: BrowserImage[];
  onWaitingForUser?: (waiting: boolean) => void;
};

export class BrowserToolError extends Error {}

type PendingPermission = {
  context: BrowserCallContext;
  resolve: (decision: PermissionDecision) => void;
  timer: NodeJS.Timeout;
};

type Sensitivity = {
  typesPassword: boolean;
  password: boolean;
  payment: boolean;
  submitsData: boolean;
  destructive: boolean;
  label: string;
};

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
  private readonly tabs = new Map<string, BrowserTab>();
  private readonly waiters = new Map<string, Array<() => void>>();
  private readonly pending = new Map<string, PendingPermission>();
  private readonly cdpApprovedTasks = new Set<string>();
  private readonly tabUrls = new Map<string, string>();
  readonly sites = new SitePolicyStore(
    () => settingsStore.get("browserSites", {}),
    (sites) => settingsStore.set("browserSites", sites),
  );

  register(input: RegisterTabInput): void {
    const contents = webContents.fromId(input.webContentsId);
    if (!contents || contents.getType() !== "webview") return;
    const tab: BrowserTab = {
      browserId: input.browserId,
      taskId: input.taskId,
      kind: input.kind,
      contents,
      console: [],
      network: [],
    };
    this.tabs.set(input.browserId, tab);
    contents.on("console-message", (event: unknown, ...legacy: unknown[]) => {
      const details = event as { message?: string; level?: string | number };
      const message =
        typeof details.message === "string"
          ? details.message
          : String(legacy[1] ?? "");
      const level = details.level ?? legacy[0] ?? "log";
      pushLog(tab.console, `[${level}] ${message}`);
    });
    contents.once("destroyed", () => {
      if (this.tabs.get(input.browserId)?.contents === contents) {
        this.tabs.delete(input.browserId);
      }
    });
    for (const resolve of this.waiters.get(input.browserId) ?? []) resolve();
    this.waiters.delete(input.browserId);
  }

  unregister(browserId: string, webContentsId: number): void {
    const tab = this.tabs.get(browserId);
    if (tab && tab.contents.id === webContentsId) this.tabs.delete(browserId);
  }

  recordNetwork(webContentsId: number | undefined, text: string): void {
    if (webContentsId === undefined) return;
    for (const tab of this.tabs.values()) {
      if (tab.contents.id === webContentsId) pushLog(tab.network, text);
    }
  }

  taskForWebContents(webContentsId: number): string | null {
    for (const tab of this.tabs.values()) {
      if (tab.contents.id === webContentsId) return tab.taskId;
    }
    return null;
  }

  requestOpen(
    taskId: string,
    url: string,
    browserId: string = randomUUID(),
  ): string {
    this.tabUrls.set(browserId, url);
    this.emit(TaskBrowserEvent.OpenRequest, { taskId, browserId, url });
    return browserId;
  }

  respondToPermission(requestId: string, decision: PermissionDecision): void {
    this.settlePrompt(requestId, decision);
  }

  settings(): { sites: Record<string, SitePolicy>; fullCdpAccess: boolean } {
    return {
      sites: this.sites.list(),
      fullCdpAccess: settingsStore.get("browserFullCdpAccess", false),
    };
  }

  async clearBrowsingData(): Promise<void> {
    const browserSession = session.fromPartition(TASK_BROWSER_PARTITION);
    await browserSession.clearStorageData();
    await browserSession.clearCache();
  }

  setFullCdpAccess(enabled: boolean): void {
    settingsStore.set("browserFullCdpAccess", enabled);
    if (!enabled) this.cdpApprovedTasks.clear();
  }

  async call(
    context: BrowserCallContext,
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
          this.press(tab, stringArg(args[1], "key")),
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
        return this.withTab(context, args[0], (tab) =>
          this.run(tab, evaluateScript(stringArg(args[1], "source"))),
        );
      case "cdp":
        return this.withTab(context, args[0], (tab) =>
          this.cdp(context, tab, stringArg(args[1], "method"), args[2]),
        );
      default:
        throw new BrowserToolError(`Unknown browser method: ${method}`);
    }
  }

  private listTabs(taskId: string) {
    return [...this.tabs.values()]
      .filter((tab) => tab.taskId === taskId && !tab.contents.isDestroyed())
      .map((tab) => ({
        id: tab.browserId,
        kind: tab.kind,
        url: tab.contents.getURL(),
        title: tab.contents.getTitle(),
      }));
  }

  private async open(context: BrowserCallContext, url: string) {
    const origin = originOf(url);
    if (!origin) throw new BrowserToolError("Only http and https URLs open.");
    await this.ensureSiteAccess(context, origin);
    const browserId = this.requestOpen(context.taskId, url);
    const tab = await this.awaitTab(browserId);
    await this.waitForLoad(tab.contents);
    return {
      id: tab.browserId,
      url: tab.contents.getURL(),
      title: tab.contents.getTitle(),
    };
  }

  private async close(taskId: string, browserId: string) {
    const tab = this.tabs.get(browserId);
    if (!tab || tab.taskId !== taskId) {
      throw new BrowserToolError(`No open tab ${browserId} in this task.`);
    }
    this.tabs.delete(browserId);
    this.tabUrls.delete(browserId);
    this.emit(TaskBrowserEvent.CloseRequest, { taskId, browserId });
    return true;
  }

  private async withTab<T>(
    context: BrowserCallContext,
    tabArg: unknown,
    action: (tab: BrowserTab) => Promise<T>,
  ): Promise<T> {
    const browserId = stringArg(tabArg, "tab");
    let tab = this.tabs.get(browserId);
    if (tab && tab.taskId !== context.taskId) {
      throw new BrowserToolError(`No open tab ${browserId} in this task.`);
    }
    if (!tab || tab.contents.isDestroyed()) {
      const url = this.tabUrls.get(browserId);
      if (!url) {
        throw new BrowserToolError(`No open tab ${browserId} in this task.`);
      }
      this.requestOpen(context.taskId, url, browserId);
      tab = await this.awaitTab(browserId);
    }
    const origin = originOf(tab.contents.getURL());
    if (origin) await this.ensureSiteAccess(context, origin);
    return action(tab);
  }

  private awaitTab(browserId: string): Promise<BrowserTab> {
    const existing = this.tabs.get(browserId);
    if (existing && !existing.contents.isDestroyed()) {
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

  private waitForLoad(contents: WebContents): Promise<void> {
    if (!contents.isLoading()) return Promise.resolve();
    return new Promise((resolve) => {
      const done = () => {
        clearTimeout(timer);
        resolve();
      };
      const timer = setTimeout(done, 10_000);
      contents.once("did-stop-loading", done);
    });
  }

  private async run<T>(tab: BrowserTab, code: string): Promise<T> {
    await this.waitForLoad(tab.contents);
    return (await tab.contents.executeJavaScriptInIsolatedWorld(PAGE_WORLD_ID, [
      { code },
    ])) as T;
  }

  private async screenshot(
    context: BrowserCallContext,
    tab: BrowserTab,
    refArg: unknown,
  ): Promise<string> {
    let rect: Electron.Rectangle | undefined;
    if (typeof refArg === "string" && refArg) {
      const box = await this.run<{
        left: number;
        top: number;
        width: number;
        height: number;
      } | null>(tab, rectScript(refArg));
      if (!box) throw new BrowserToolError(`No element ${refArg} on the page.`);
      const zoom = tab.contents.getZoomFactor();
      rect = {
        x: Math.max(0, Math.round(box.left * zoom)),
        y: Math.max(0, Math.round(box.top * zoom)),
        width: Math.max(1, Math.round(box.width * zoom)),
        height: Math.max(1, Math.round(box.height * zoom)),
      };
    }
    const image = await this.capture(tab, rect);
    const { width } = image.getSize();
    const resized =
      width > SCREENSHOT_MAX_WIDTH
        ? image.resize({ width: SCREENSHOT_MAX_WIDTH })
        : image;
    context.images.push({
      data: resized.toJPEG(SCREENSHOT_QUALITY).toString("base64"),
      mimeType: "image/jpeg",
    });
    return `screenshot ${context.images.length} attached`;
  }

  private async capture(tab: BrowserTab, rect: Electron.Rectangle | undefined) {
    const attempt = () =>
      Promise.race([
        tab.contents.capturePage(rect).catch(() => null),
        new Promise<null>((resolve) =>
          setTimeout(() => resolve(null), CAPTURE_TIMEOUT_MS),
        ),
      ]);
    const image = await attempt();
    if (image && !image.isEmpty()) return image;
    if (tab.kind !== "browser") {
      throw new BrowserToolError(
        "The preview is not on screen. Ask the user to open it, then try again.",
      );
    }
    this.requestOpen(tab.taskId, tab.contents.getURL(), tab.browserId);
    await new Promise((resolve) => setTimeout(resolve, 400));
    const retry = await attempt();
    if (!retry || retry.isEmpty()) {
      throw new BrowserToolError("The tab could not be captured. Try again.");
    }
    return retry;
  }

  private async point(tab: BrowserTab, ref: string) {
    const box = await this.run<{ x: number; y: number } | null>(
      tab,
      rectScript(ref),
    );
    if (!box) throw new BrowserToolError(`No element ${ref} on the page.`);
    const zoom = tab.contents.getZoomFactor();
    return { x: Math.round(box.x * zoom), y: Math.round(box.y * zoom) };
  }

  private async click(
    context: BrowserCallContext,
    tab: BrowserTab,
    ref: string,
  ) {
    const sensitivity = await this.run<Sensitivity | null>(
      tab,
      sensitivityScript(ref),
    );
    if (!sensitivity)
      throw new BrowserToolError(`No element ${ref} on the page.`);
    const origin = originOf(tab.contents.getURL()) ?? "this page";
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
    tab.contents.focus();
    tab.contents.sendInputEvent({ type: "mouseMove", x, y });
    tab.contents.sendInputEvent({
      type: "mouseDown",
      x,
      y,
      button: "left",
      clickCount: 1,
    });
    tab.contents.sendInputEvent({
      type: "mouseUp",
      x,
      y,
      button: "left",
      clickCount: 1,
    });
    await this.settle(tab);
    return true;
  }

  private async type(
    context: BrowserCallContext,
    tab: BrowserTab,
    ref: string,
    text: string,
    clear: boolean,
  ) {
    const sensitivity = await this.run<Sensitivity | null>(
      tab,
      sensitivityScript(ref),
    );
    if (!sensitivity)
      throw new BrowserToolError(`No element ${ref} on the page.`);
    const origin = originOf(tab.contents.getURL()) ?? "this page";
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
    tab.contents.focus();
    if (clear) {
      tab.contents.sendInputEvent({ type: "keyDown", keyCode: "Backspace" });
      tab.contents.sendInputEvent({ type: "keyUp", keyCode: "Backspace" });
    }
    if (text) tab.contents.insertText(text);
    return true;
  }

  private async press(tab: BrowserTab, key: string) {
    tab.contents.focus();
    tab.contents.sendInputEvent({ type: "keyDown", keyCode: key });
    if (key.length === 1)
      tab.contents.sendInputEvent({ type: "char", keyCode: key });
    tab.contents.sendInputEvent({ type: "keyUp", keyCode: key });
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
    context: BrowserCallContext,
    tab: BrowserTab,
    target: string,
  ) {
    const contents = tab.contents;
    if (target === "back") {
      if (contents.navigationHistory.canGoBack())
        contents.navigationHistory.goBack();
    } else if (target === "forward") {
      if (contents.navigationHistory.canGoForward())
        contents.navigationHistory.goForward();
    } else if (target === "reload") {
      contents.reload();
    } else {
      const next = new URL(target, contents.getURL());
      const origin = originOf(next.toString());
      if (!origin) throw new BrowserToolError("Only http and https URLs open.");
      if (tab.kind === "preview" && origin !== originOf(contents.getURL())) {
        throw new BrowserToolError(
          "A preview tab stays on its own site. Open other sites with browser.open.",
        );
      }
      await this.ensureSiteAccess(context, origin);
      await contents.loadURL(next.toString()).catch(() => undefined);
    }
    await this.settle(tab);
    return { url: contents.getURL(), title: contents.getTitle() };
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
    context: BrowserCallContext,
    tab: BrowserTab,
    method: string,
    params: unknown,
  ) {
    if (!settingsStore.get("browserFullCdpAccess", false)) {
      throw new BrowserToolError(
        "Full CDP access is off. The user can turn it on in Settings > Browser.",
      );
    }
    if (!isTabScopedCdpMethod(method)) {
      throw new BrowserToolError(
        `${method} is not available because it reaches beyond this tab.`,
      );
    }
    if (method === "Page.navigate") {
      const target = (params as { url?: unknown } | null)?.url;
      const origin = typeof target === "string" ? originOf(target) : null;
      if (!origin) {
        throw new BrowserToolError("Page.navigate needs an http or https URL.");
      }
      await this.ensureSiteAccess(context, origin);
    }
    if (!this.cdpApprovedTasks.has(context.taskId)) {
      await this.confirm(
        context,
        "full-cdp",
        originOf(tab.contents.getURL()) ?? "",
        ["Use the Chrome DevTools Protocol on this tab"],
      );
      this.cdpApprovedTasks.add(context.taskId);
    }
    const debuggerApi = tab.contents.debugger;
    if (!debuggerApi.isAttached()) debuggerApi.attach("1.3");
    return debuggerApi.sendCommand(
      method,
      params && typeof params === "object"
        ? (params as Record<string, unknown>)
        : {},
    );
  }

  private async settle(tab: BrowserTab) {
    await new Promise((resolve) => setTimeout(resolve, 150));
    await this.waitForLoad(tab.contents);
  }

  private async ensureSiteAccess(context: BrowserCallContext, origin: string) {
    const taskId = context.taskId;
    const access = this.sites.access(taskId, origin);
    if (access === "allowed") return;
    if (access === "blocked") {
      throw new BrowserToolError(`The user blocked ${origin} for the agent.`);
    }
    const decision = await this.ask(context, "site", origin, `Use ${origin}`);
    if (decision === "allow-always") this.sites.set(origin, "allow");
    else if (decision === "block") this.sites.set(origin, "block");
    if (
      decision === "allow-task" ||
      decision === "allow-always" ||
      decision === "allow-once"
    ) {
      this.sites.approveForTask(taskId, origin);
      return;
    }
    throw new BrowserToolError(
      `The user did not allow the agent to use ${origin}.`,
    );
  }

  private async confirm(
    context: BrowserCallContext,
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

  cancelPrompts(context: BrowserCallContext): void {
    for (const [requestId, pending] of this.pending) {
      if (pending.context === context) this.settlePrompt(requestId, "deny");
    }
  }

  private settlePrompt(requestId: string, decision: PermissionDecision) {
    const pending = this.pending.get(requestId);
    if (!pending) return;
    clearTimeout(pending.timer);
    this.pending.delete(requestId);
    pending.context.onWaitingForUser?.(false);
    this.emit(TaskBrowserEvent.PermissionSettled, { requestId });
    pending.resolve(decision);
  }

  private ask(
    context: BrowserCallContext,
    kind: PermissionKind,
    origin: string,
    detail: string,
  ): Promise<PermissionDecision> {
    const requestId = randomUUID();
    return new Promise((resolve) => {
      const timer = setTimeout(
        () => this.settlePrompt(requestId, "deny"),
        PERMISSION_TIMEOUT_MS,
      );
      this.pending.set(requestId, { context, resolve, timer });
      context.onWaitingForUser?.(true);
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
