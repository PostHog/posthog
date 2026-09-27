import path from "node:path";
import { BrowserWindow, ipcMain, session } from "electron";
import {
  BROWSER_RUNNER_ARG,
  BROWSER_RUNNER_CALL_CHANNEL,
  BROWSER_RUNNER_DONE_CHANNEL,
  BROWSER_RUNNER_PARTITION,
  BROWSER_RUNNER_RUN_CHANNEL,
} from "../../../shared/constants";
import {
  type BrowserCallContext,
  type BrowserImage,
  BrowserToolError,
  type TaskBrowserService,
} from "./service";

const RUN_TIMEOUT_MS = 90_000;
const MAX_CALLS_PER_RUN = 300;
const MAX_OUTPUT_CHARS = 60_000;

export type BrowserRunResult = {
  ok: boolean;
  output: string;
  images: BrowserImage[];
};

const RUNNER_PAGE = `<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval'; worker-src 'none'; child-src 'none'"></head><body><script>
const host = window.phBrowserHost;
const logs = [];
const format = (value) => typeof value === "string" ? value : (() => { try { return JSON.stringify(value, null, 2); } catch { return String(value); } })();
for (const level of ["log", "info", "warn", "error"]) {
  console[level] = (...values) => logs.push(values.map(format).join(" "));
}
const call = async (method, ...args) => {
  try {
    return await host.call(method, args);
  } catch (error) {
    const message = String(error && error.message || error).replace(/^Error invoking remote method '[^']*': (Error: )?/, "");
    throw new Error(message);
  }
};
const tabApi = (id) => ({
  id,
  snapshot: () => call("snapshot", id),
  find: (text) => call("find", id, text),
  screenshot: (ref) => call("screenshot", id, ref),
  click: (ref) => call("click", id, ref),
  type: (ref, text, options) => call("type", id, ref, text, !!(options && options.clear)),
  press: (key) => call("press", id, key),
  scroll: (deltaY) => call("scroll", id, deltaY),
  navigate: (target) => call("navigate", id, target),
  waitFor: (text, timeoutMs) => call("waitFor", id, text, timeoutMs),
  console: (since) => call("console", id, since),
  network: (since) => call("network", id, since),
  evaluate: (fn) => call("evaluate", id, typeof fn === "function" ? fn.toString() : String(fn)),
  cdp: (method, params) => call("cdp", id, method, params),
  close: () => call("close", id),
});
const browser = {
  tabs: async () => (await call("tabs")).map((tab) => ({ ...tab, ...tabApi(tab.id) })),
  open: async (url) => { const tab = await call("open", url); return { ...tab, ...tabApi(tab.id) }; },
  tab: (id) => tabApi(id),
};
host.onRun(async (code) => {
  const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
  try {
    const result = await new AsyncFunction("browser", code)(browser);
    if (result !== undefined) logs.push(format(result));
    host.done({ ok: true, output: logs.join("\\n") });
  } catch (error) {
    logs.push("Error: " + String(error && error.message || error));
    host.done({ ok: false, output: logs.join("\\n") });
  }
});
</script></body></html>`;

let runnerSessionReady = false;

function runnerSession(): Electron.Session {
  const runner = session.fromPartition(BROWSER_RUNNER_PARTITION);
  if (!runnerSessionReady) {
    runnerSessionReady = true;
    runner.setPermissionRequestHandler((_c, _p, callback) => callback(false));
    runner.setPermissionCheckHandler(() => false);
    runner.webRequest.onBeforeRequest((details, callback) =>
      callback({ cancel: !details.url.startsWith("data:") }),
    );
  }
  return runner;
}

type ActiveRun = {
  context: BrowserCallContext;
  calls: number;
  finish: (result: { ok: boolean; output: string }) => void;
};

export class BrowserRunner {
  private readonly runs = new Map<number, ActiveRun>();

  constructor(private readonly service: TaskBrowserService) {
    ipcMain.handle(
      BROWSER_RUNNER_CALL_CHANNEL,
      async (event, method: unknown, args: unknown) => {
        const run = this.runs.get(event.sender.id);
        if (!run) throw new BrowserToolError("Unknown caller.");
        run.calls += 1;
        if (run.calls > MAX_CALLS_PER_RUN) {
          throw new BrowserToolError(
            `More than ${MAX_CALLS_PER_RUN} browser calls in one run.`,
          );
        }
        if (typeof method !== "string" || !Array.isArray(args)) {
          throw new BrowserToolError("Malformed browser call.");
        }
        return this.service.call(run.context, method, args);
      },
    );
    ipcMain.on(BROWSER_RUNNER_DONE_CHANNEL, (event, result: unknown) => {
      const value = result as { ok?: unknown; output?: unknown };
      this.runs.get(event.sender.id)?.finish({
        ok: value?.ok === true,
        output: typeof value?.output === "string" ? value.output : "",
      });
    });
  }

  run(taskId: string, code: string): Promise<BrowserRunResult> {
    const context: BrowserCallContext = { taskId, images: [] };
    const window = new BrowserWindow({
      show: false,
      webPreferences: {
        session: runnerSession(),
        sandbox: true,
        contextIsolation: true,
        nodeIntegration: false,
        webviewTag: false,
        preload: path.join(__dirname, "preload.js"),
        additionalArguments: [BROWSER_RUNNER_ARG],
      },
    });
    const contents = window.webContents;
    const contentsId = contents.id;

    return new Promise<BrowserRunResult>((resolve) => {
      let settled = false;
      let remaining = RUN_TIMEOUT_MS;
      let startedAt = Date.now();
      let waitingForUser = 0;
      const onTimeout = () =>
        finish({
          ok: false,
          output: `Error: the code ran longer than ${RUN_TIMEOUT_MS / 1000} s.`,
        });
      let timer = setTimeout(onTimeout, remaining);
      context.onWaitingForUser = (waiting) => {
        if (settled) return;
        if (waiting) {
          waitingForUser += 1;
          if (waitingForUser > 1) return;
          clearTimeout(timer);
          remaining -= Date.now() - startedAt;
          return;
        }
        waitingForUser = Math.max(0, waitingForUser - 1);
        if (waitingForUser > 0) return;
        startedAt = Date.now();
        timer = setTimeout(onTimeout, Math.max(remaining, 0));
      };
      const finish = (result: { ok: boolean; output: string }) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        this.service.cancelPrompts(context);
        this.runs.delete(contentsId);
        if (!window.isDestroyed()) window.destroy();
        const output =
          result.output.length > MAX_OUTPUT_CHARS
            ? `${result.output.slice(0, MAX_OUTPUT_CHARS)}\n… output truncated`
            : result.output;
        resolve({ ok: result.ok, output, images: context.images });
      };
      this.runs.set(contentsId, { context, calls: 0, finish });
      contents.once("render-process-gone", () =>
        finish({
          ok: false,
          output: "Error: the code runner stopped unexpectedly.",
        }),
      );
      contents.once("did-finish-load", () =>
        contents.send(BROWSER_RUNNER_RUN_CHANNEL, code),
      );
      void window
        .loadURL(
          `data:text/html;charset=utf-8,${encodeURIComponent(RUNNER_PAGE)}`,
        )
        .catch((error: unknown) =>
          finish({ ok: false, output: `Error: ${String(error)}` }),
        );
    });
  }
}
