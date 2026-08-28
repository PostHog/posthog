/**
 * Adapter-agnostic ACP driver for the live e2e suite. Stands up the same in-process
 * ACP transport the real host uses and drives a real adapter + binary + gateway.
 * The only thing mocked is the host/UI client (recording sessionUpdate, auto-allow
 * requestPermission, real fs read/write against the test repo).
 */
import { execFileSync } from "node:child_process";
import {
  promises as fsp,
  mkdtempSync,
  readFileSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
// @ts-expect-error - runtime ESM export resolved by vitest
import { ClientSideConnection, ndJsonStream } from "@agentclientprotocol/sdk";
import { createAcpConnection } from "../src/adapters/acp-connection";
import { Logger } from "../src/utils/logger";
import { type Adapter, E2E } from "./config";

export type { Adapter } from "./config";

export interface CapturedEvent {
  kind: "sessionUpdate" | "requestPermission" | "extNotification";
  sessionUpdate?: string;
  method?: string;
  data?: Record<string, unknown>;
}

export interface Capture {
  events: CapturedEvent[];
  updates(type: string): CapturedEvent[];
  approvals(): CapturedEvent[];
  extMethods(): string[];
}

export interface NewSessionResponse {
  sessionId: string;
  configOptions?: ConfigOption[];
  modes?: unknown;
}

export interface ConfigOption {
  id?: string;
  category?: string;
  currentValue?: unknown;
  options?: Array<{ name?: string; value?: unknown }>;
}

export interface AcpConn {
  initialize: (p: unknown) => Promise<any>;
  newSession: (p: unknown) => Promise<NewSessionResponse>;
  loadSession: (p: unknown) => Promise<any>;
  resumeSession: (p: unknown) => Promise<any>;
  listSessions: (
    p: unknown,
  ) => Promise<{ sessions?: Array<{ sessionId?: string }> }>;
  unstable_forkSession: (p: unknown) => Promise<NewSessionResponse>;
  prompt: (p: unknown) => Promise<{ stopReason?: string; usage?: unknown }>;
  setSessionConfigOption: (p: unknown) => Promise<any>;
  cancel: (p: unknown) => Promise<void>;
  // Client→agent ext-method (the host drives _posthog/refresh_session).
  extMethod: (method: string, params: unknown) => Promise<unknown>;
}

export interface E2EConnection {
  conn: AcpConn;
  capture: Capture;
  cleanup: () => Promise<void>;
}

/**
 * The ACP `initialize` params our host client sends. Matches the cloud host, which
 * advertises no clientCapabilities — so the adapter runs file/terminal tools
 * in-process rather than proxying through the host's fs callbacks.
 */
export const INIT_PARAMS = {
  protocolVersion: 1,
  clientCapabilities: {},
};

export function openConnection(opts: {
  adapter: Adapter;
  cwd: string;
  codexOptions?: Record<string, unknown>;
  onStructuredOutput?: (output: Record<string, unknown>) => Promise<void>;
}): E2EConnection {
  const { adapter, cwd } = opts;
  // Sweep before every codex spawn so one leaked process (holding the
  // ~/.codex/tmp flock) cannot wedge the rest of the run.
  if (adapter === "codex") killCodexStragglers();
  const events: CapturedEvent[] = [];

  // Mirror the cloud host's client surface. Deliberately no extMethod: the real
  // host doesn't implement it, so an adapter calling it should fail e2e as in prod.
  const client = {
    async sessionUpdate(p: any): Promise<void> {
      events.push({
        kind: "sessionUpdate",
        sessionUpdate: p?.update?.sessionUpdate,
        data: p?.update,
      });
    },
    async requestPermission(p: any): Promise<unknown> {
      events.push({
        kind: "requestPermission",
        data: {
          title: p?.toolCall?.title,
          kind: p?.toolCall?.kind,
          // request_user_input surfaces as a permission with codeToolKind: "question"; codex only offers it in Plan mode.
          codeToolKind: p?.toolCall?._meta?.codeToolKind,
        },
      });
      const options = p?.options ?? [];
      const allow =
        options.find(
          (o: any) => o?.kind === "allow_once" || o?.kind === "allow_always",
        ) ?? options[0];
      return {
        outcome: { outcome: "selected", optionId: allow?.optionId ?? "allow" },
      };
    },
    async readTextFile(p: any): Promise<unknown> {
      return { content: await fsp.readFile(resolve(cwd, p.path), "utf8") };
    },
    async writeTextFile(p: any): Promise<unknown> {
      await fsp.writeFile(resolve(cwd, p.path), p.content);
      return {};
    },
    async extNotification(method: string, params: any): Promise<void> {
      events.push({ kind: "extNotification", method, data: params });
    },
  };

  const logger = new Logger({
    debug: !!process.env.E2E_DEBUG,
    prefix: "[e2e]",
  });
  const acp = createAcpConnection({
    adapter,
    codexOptions: opts.codexOptions as any,
    onStructuredOutput: opts.onStructuredOutput,
    logger,
  });
  const stream = ndJsonStream(
    acp.clientStreams.writable,
    acp.clientStreams.readable,
  );
  const conn = new ClientSideConnection(
    () => client,
    stream,
  ) as unknown as AcpConn;

  const capture: Capture = {
    events,
    updates: (type) =>
      events.filter(
        (e) => e.kind === "sessionUpdate" && e.sessionUpdate === type,
      ),
    approvals: () => events.filter((e) => e.kind === "requestPermission"),
    extMethods: () => [
      ...new Set(
        events
          .filter((e) => e.kind === "extNotification" && e.method)
          .map((e) => e.method as string),
      ),
    ],
  };

  return {
    conn,
    capture,
    cleanup: async () => {
      // Bounded: a wedged adapter cleanup must never hang the suite.
      await Promise.race([
        acp.cleanup().catch(() => undefined),
        new Promise<void>((r) => setTimeout(r, 8000)),
      ]);
    },
  };
}

export interface OpenSession {
  conn: AcpConn;
  capture: Capture;
  sessionId: string;
  newSession: NewSessionResponse;
  cleanup: () => Promise<void>;
}

/** openConnection + initialize + newSession — the common scenario setup. */
export async function openSession(opts: {
  adapter: Adapter;
  cwd: string;
  codexOptions?: Record<string, unknown>;
  onStructuredOutput?: (output: Record<string, unknown>) => Promise<void>;
  meta: Record<string, unknown>;
}): Promise<OpenSession> {
  const c = openConnection(opts);
  // initialize/newSession hit a live gateway; on failure the caller never gets
  // a cleanup handle, so clean up here or the spawned adapter process leaks.
  try {
    await c.conn.initialize(INIT_PARAMS);
    const newSession = await c.conn.newSession({
      cwd: opts.cwd,
      mcpServers: [],
      // Inject POSTHOG_CODE_E2E_ENVIRONMENT so the suite can run as a cloud session without threading it through every test's meta.
      _meta: {
        ...opts.meta,
        ...(E2E.environment ? { environment: E2E.environment } : {}),
      },
    });
    return {
      conn: c.conn,
      capture: c.capture,
      sessionId: newSession.sessionId,
      newSession,
      cleanup: c.cleanup,
    };
  } catch (err) {
    await c.cleanup();
    throw err;
  }
}

export const ORIGINAL_TARGET = "line1\nline2\nline3\n";

export function setupRepo(): string {
  // realpath so cwd is canonical: on macOS os.tmpdir() is a symlink. The Claude
  // SDK keys its session store by the resolved path, so loadSession's replay finds
  // nothing if a fresh connection uses a different path.
  const repo = realpathSync(mkdtempSync(join(tmpdir(), "agent-e2e-")));
  writeFileSync(join(repo, "target.txt"), ORIGINAL_TARGET);
  execFileSync("git", ["init", "-q"], { cwd: repo });
  execFileSync("git", ["add", "-A"], { cwd: repo });
  // -c commit.gpgsign=false: ignore the user's global signing config, which fails in this non-interactive context.
  execFileSync(
    "git",
    [
      "-c",
      "commit.gpgsign=false",
      "-c",
      "user.email=e2e@posthog.dev",
      "-c",
      "user.name=e2e",
      "commit",
      "-qm",
      "init",
    ],
    { cwd: repo },
  );
  return repo;
}

export function readTarget(repo: string): string {
  return readFileSync(join(repo, "target.txt"), "utf8");
}

export function cleanupRepo(repo: string): void {
  try {
    rmSync(repo, { recursive: true, force: true });
  } catch {
    /* best effort */
  }
}

/** Poll `fn` until it returns a non-undefined value or the timeout elapses. */
export async function waitFor<T>(
  fn: () => T | undefined,
  timeoutMs = 5000,
  intervalMs = 100,
): Promise<T | undefined> {
  const start = Date.now();
  for (;;) {
    const value = fn();
    if (value !== undefined) return value;
    if (Date.now() - start >= timeoutMs) return undefined;
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}

/**
 * codex spawns detached; a killed run can orphan it holding a flock under
 * ~/.codex/tmp, wedging the next run. Kill stragglers first to release the
 * flock. Matched on THIS checkout's absolute resources path so a concurrent
 * run from another checkout (or a dev's real session) is never killed.
 */
export function killCodexStragglers(): void {
  try {
    execFileSync("pkill", ["-9", "-f", E2E.codexResourcesDir], {
      stdio: "ignore",
    });
  } catch {
    /* none running */
  }
}
