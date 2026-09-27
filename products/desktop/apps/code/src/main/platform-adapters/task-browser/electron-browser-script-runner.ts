import path from "node:path";
import type {
  BrowserScriptResult,
  BrowserScriptRun,
  IBrowserScriptRunner,
} from "@posthog/platform/task-browser";
import { BrowserWindow, ipcMain, session } from "electron";
import { injectable } from "inversify";
import {
  BROWSER_RUNNER_ARG,
  BROWSER_RUNNER_CALL_CHANNEL,
  BROWSER_RUNNER_DONE_CHANNEL,
  BROWSER_RUNNER_PARTITION,
  BROWSER_RUNNER_RUN_CHANNEL,
} from "../../../shared/constants";

type BrowserCall = (method: string, args: unknown[]) => Promise<unknown>;

type ActiveRun = {
  call: BrowserCall;
  finish: (result: BrowserScriptResult) => void;
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

@injectable()
export class ElectronBrowserScriptRunner implements IBrowserScriptRunner {
  private readonly runs = new Map<number, ActiveRun>();

  constructor() {
    ipcMain.handle(
      BROWSER_RUNNER_CALL_CHANNEL,
      async (event, method: unknown, args: unknown) => {
        const run = this.runs.get(event.sender.id);
        if (!run) throw new Error("Unknown caller.");
        if (typeof method !== "string" || !Array.isArray(args)) {
          throw new Error("Malformed browser call.");
        }
        return run.call(method, args);
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

  start(code: string, call: BrowserCall): BrowserScriptRun {
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
    let finish: (result: BrowserScriptResult) => void = () => undefined;
    const stop = () => {
      this.runs.delete(contentsId);
      if (!window.isDestroyed()) window.destroy();
    };
    const done = new Promise<BrowserScriptResult>((resolve) => {
      finish = (result) => {
        stop();
        resolve(result);
      };
    });
    this.runs.set(contentsId, { call, finish });
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
    return { done, stop };
  }
}
