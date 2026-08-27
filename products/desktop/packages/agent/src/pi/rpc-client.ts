import { type ChildProcess, spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import type { Writable } from "node:stream";
import { StringDecoder } from "node:string_decoder";
import { fileURLToPath } from "node:url";
import {
  type JsonAgentSessionEvent,
  RpcClient,
  type RpcClientOptions,
  type RpcEventListener,
} from "@earendil-works/pi-coding-agent";
import type { McpConfig } from "@posthog/harness/extensions/mcp/config";
import type {
  McpServerConnection,
  McpToolPermissionDecision,
  McpToolPermissionRequest,
  McpToolPolicy,
} from "@posthog/shared";
import type { PiEnrichmentConfig } from "./enrichment-extension";
import { safePiEnvironment } from "./rpc-environment";
import type { TaskContext } from "./task-system-prompt";
import type {
  PiExtensionEvent,
  PiQueueSnapshot,
  RpcExtensionUIResponse,
} from "./types";

export type PiRpcEvent = JsonAgentSessionEvent | PiExtensionEvent;
export type PiRuntimeExtension =
  | "repository-tools"
  | "auto-publish"
  | "context-wiki";

type PiRpcEventListener = (event: PiRpcEvent) => void;

export type PiRpcClient = RpcClient & {
  onEvent(listener: PiRpcEventListener): () => void;
  getQueue(): Promise<PiQueueSnapshot>;
  clearQueue(): Promise<PiQueueSnapshot>;
  onMcpToolPermissionRequest(
    listener: (request: McpToolPermissionRequest) => void,
  ): () => void;
  respondMcpToolPermission(
    requestId: string,
    decision: McpToolPermissionDecision,
  ): void;
  respondToExtensionUI(response: RpcExtensionUIResponse): Promise<void>;
};

export interface PiRpcProviderOptions {
  region?: "us" | "eu" | "dev";
  apiKey: string;
  baseUrl?: string;
  headers?: Record<string, string>;
}

export interface PiRpcBootstrap {
  providerOptions: PiRpcProviderOptions;
  enrichment?: PiEnrichmentConfig;
  runtimeMcpServers?: PiRuntimeMcpServers;
  mcpToolPolicies?: McpToolPolicy[];
  projectTrusted?: boolean;
  taskContext: TaskContext;
  extensions?: PiRuntimeExtension[];
  /** Local checkout of the org's context wiki, when one is mounted. */
  contextWikiPath?: string;
}

type RpcClientProcessAccess = {
  process?: ChildProcess;
};

interface RpcClientInternals {
  process?: ChildProcess;
  stopReadingStdout?: () => void;
  stderr: string;
  exitError: Error | null;
  handleLine(line: string): void;
  createProcessExitError(
    code: number | null,
    signal: NodeJS.Signals | null,
  ): Error;
  rejectPendingRequests(error: Error): void;
}

export type PiRuntimeMcpServers = McpConfig["mcpServers"];

export interface PiStdioMcpServer {
  name: string;
  command: string;
  args?: string[];
  env?: Array<{ name: string; value: string }>;
}

// Signed git may use three 30-second GitHub attempts before reporting task activity.
// The client deadline must not report failure while the MCP child continues the push.
const LOCAL_STDIO_MCP_REQUEST_TIMEOUT_MS = 5 * 60_000;

export function createRuntimeMcpServers(
  servers: McpServerConnection[],
): PiRuntimeMcpServers {
  return Object.fromEntries(
    servers.map((server) => [
      server.name,
      {
        transport:
          server.type === "http"
            ? ("streamable-http" as const)
            : ("sse" as const),
        url: server.url,
        headers: Object.fromEntries(
          (server.headers ?? []).map((header) => [header.name, header.value]),
        ),
        lifecycle: "lazy" as const,
        args: [],
        directTools: false,
      },
    ]),
  );
}

export function createRuntimeMcpStdioServers(
  servers: PiStdioMcpServer[],
): PiRuntimeMcpServers {
  return Object.fromEntries(
    servers.map((server) => [
      server.name,
      {
        command: server.command,
        args: server.args ?? [],
        env: Object.fromEntries(
          (server.env ?? []).map((variable) => [variable.name, variable.value]),
        ),
        transport: "stdio" as const,
        lifecycle: "eager" as const,
        requestTimeoutMs: LOCAL_STDIO_MCP_REQUEST_TIMEOUT_MS,
        directTools: true,
      },
    ]),
  );
}

interface PiHostRequest {
  type: "posthog_pi_host_request";
  id: string;
  method: "get_queue" | "clear_queue";
}

interface PiMcpPermissionRequestMessage {
  type: "posthog_pi_mcp_permission_request";
  request: McpToolPermissionRequest;
}

interface PiMcpPermissionResponseMessage {
  type: "posthog_pi_mcp_permission_response";
  requestId: string;
  decision: McpToolPermissionDecision;
}

interface PiHostResponse {
  type: "posthog_pi_host_response";
  id: string;
  data?: PiQueueSnapshot;
  error?: string;
}

function attachJsonlReader(
  stream: NodeJS.ReadableStream,
  onLine: (line: string) => void,
): () => void {
  const decoder = new StringDecoder("utf8");
  let buffer = "";
  const onData = (chunk: Buffer | string) => {
    buffer += typeof chunk === "string" ? chunk : decoder.write(chunk);
    let newlineIndex = buffer.indexOf("\n");
    while (newlineIndex !== -1) {
      const line = buffer.slice(0, newlineIndex);
      onLine(line.endsWith("\r") ? line.slice(0, -1) : line);
      buffer = buffer.slice(newlineIndex + 1);
      newlineIndex = buffer.indexOf("\n");
    }
  };
  stream.on("data", onData);
  return () => stream.off("data", onData);
}

class SecurePiRpcClient extends RpcClient {
  private readonly mcpPermissionListeners = new Set<
    (request: McpToolPermissionRequest) => void
  >();
  private readonly hostRequests = new Map<
    string,
    {
      resolve: (snapshot: PiQueueSnapshot) => void;
      reject: (error: Error) => void;
      timeout: ReturnType<typeof setTimeout>;
    }
  >();

  constructor(
    private readonly secureOptions: RpcClientOptions,
    private readonly bootstrap: PiRpcBootstrap,
  ) {
    super(secureOptions);
  }

  onEvent(listener: PiRpcEventListener): () => void;
  override onEvent(listener: RpcEventListener): () => void;
  override onEvent(
    listener: PiRpcEventListener | RpcEventListener,
  ): () => void {
    return super.onEvent((event) => listener(event));
  }

  override async start(): Promise<void> {
    const internals = this as unknown as RpcClientInternals;
    if (internals.process) {
      throw new Error("Pi RPC client is already started");
    }

    internals.exitError = null;
    const args = ["--mode", "rpc"];
    if (this.secureOptions.provider) {
      args.push("--provider", this.secureOptions.provider);
    }
    if (this.secureOptions.model) {
      args.push("--model", this.secureOptions.model);
    }
    if (this.secureOptions.args) {
      args.push(...this.secureOptions.args);
    }

    const child = spawn(
      process.execPath,
      [this.secureOptions.cliPath ?? "dist/cli.js", ...args],
      {
        cwd: this.secureOptions.cwd,
        env: {
          ...safePiEnvironment(process.env),
          ELECTRON_RUN_AS_NODE: "1",
        },
        stdio: ["pipe", "pipe", "pipe", "pipe", "ipc"],
      },
    );
    internals.process = child;

    child.stderr?.on("data", (data: Buffer) => {
      internals.stderr += data.toString();
      process.stderr.write(data);
    });
    child.once("exit", (code, signal) => {
      if (internals.process !== child) {
        return;
      }
      const error = internals.createProcessExitError(code, signal);
      internals.exitError = error;
      internals.rejectPendingRequests(error);
      this.rejectHostRequests(error);
    });
    child.on("message", (message: unknown) => {
      this.handleHostResponse(message);
      this.handleMcpPermissionRequest(message);
    });
    child.once("error", (error) => {
      if (internals.process !== child) {
        return;
      }
      const processError = new Error(
        `Agent process error: ${error.message}. Stderr: ${internals.stderr}`,
      );
      internals.exitError = processError;
      internals.rejectPendingRequests(processError);
    });
    child.stdin?.on("error", (error) => {
      const stdinError =
        internals.exitError ??
        new Error(
          `Agent process stdin error: ${error.message}. Stderr: ${internals.stderr}`,
        );
      internals.exitError = stdinError;
      internals.rejectPendingRequests(stdinError);
    });
    if (child.stdout) {
      internals.stopReadingStdout = attachJsonlReader(child.stdout, (line) =>
        internals.handleLine(line),
      );
    }

    const bootstrapPipe = child.stdio[3] as Writable | null;
    bootstrapPipe?.on("error", () => {});
    bootstrapPipe?.end(JSON.stringify(this.bootstrap));

    await new Promise((resolve) => setTimeout(resolve, 100));
    if (child.exitCode !== null) {
      throw (
        internals.exitError ??
        internals.createProcessExitError(child.exitCode, child.signalCode)
      );
    }
  }

  getQueue(): Promise<PiQueueSnapshot> {
    return this.sendHostRequest("get_queue");
  }

  clearQueue(): Promise<PiQueueSnapshot> {
    return this.sendHostRequest("clear_queue");
  }

  respondToExtensionUI(response: RpcExtensionUIResponse): Promise<void> {
    const child = (this as unknown as RpcClientInternals).process;
    const stdin = child?.stdin;
    if (!child || !stdin || stdin.destroyed || !stdin.writable) {
      return Promise.reject(new Error("Pi RPC client is not writable"));
    }

    return new Promise((resolve, reject) => {
      stdin.write(`${JSON.stringify(response)}\n`, (error) => {
        if (error) {
          reject(error);
        } else {
          resolve();
        }
      });
    });
  }

  private sendHostRequest(
    method: PiHostRequest["method"],
  ): Promise<PiQueueSnapshot> {
    const process = (this as unknown as RpcClientInternals).process;
    if (!process?.connected) {
      return Promise.reject(new Error("Pi RPC host is not connected"));
    }

    const id = randomUUID();
    const request: PiHostRequest = {
      type: "posthog_pi_host_request",
      id,
      method,
    };

    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.hostRequests.delete(id);
        reject(new Error(`Pi RPC host request timed out: ${method}`));
      }, 10_000);
      this.hostRequests.set(id, { resolve, reject, timeout });
      process.send?.(request, (error) => {
        if (!error) {
          return;
        }
        const pending = this.hostRequests.get(id);
        if (pending) {
          clearTimeout(pending.timeout);
          this.hostRequests.delete(id);
        }
        reject(error);
      });
    });
  }

  private handleHostResponse(message: unknown): void {
    const response = message as Partial<PiHostResponse>;
    if (
      response.type !== "posthog_pi_host_response" ||
      typeof response.id !== "string"
    ) {
      return;
    }

    const request = this.hostRequests.get(response.id);
    if (!request) {
      return;
    }
    this.hostRequests.delete(response.id);
    clearTimeout(request.timeout);

    if (typeof response.error === "string") {
      request.reject(new Error(response.error));
      return;
    }
    if (!response.data) {
      request.reject(new Error("Pi RPC host returned an empty queue response"));
      return;
    }
    request.resolve(response.data);
  }

  onMcpToolPermissionRequest(
    listener: (request: McpToolPermissionRequest) => void,
  ): () => void {
    this.mcpPermissionListeners.add(listener);
    return () => this.mcpPermissionListeners.delete(listener);
  }

  respondMcpToolPermission(
    requestId: string,
    decision: McpToolPermissionDecision,
  ): void {
    const child = (this as unknown as RpcClientProcessAccess).process;
    child?.send({
      type: "posthog_pi_mcp_permission_response",
      requestId,
      decision,
    } satisfies PiMcpPermissionResponseMessage);
  }

  private handleMcpPermissionRequest(message: unknown): void {
    const permissionMessage = message as Partial<PiMcpPermissionRequestMessage>;
    if (
      permissionMessage.type !== "posthog_pi_mcp_permission_request" ||
      !permissionMessage.request
    ) {
      return;
    }

    for (const listener of this.mcpPermissionListeners) {
      listener(permissionMessage.request);
    }
  }

  private rejectHostRequests(error: Error): void {
    for (const request of this.hostRequests.values()) {
      clearTimeout(request.timeout);
      request.reject(error);
    }
    this.hostRequests.clear();
  }
}

export function getPiRpcClientProcess(
  client: PiRpcClient,
): ChildProcess | null {
  return (client as unknown as RpcClientProcessAccess).process ?? null;
}

export type PiRpcClientOptions = Pick<RpcClientOptions, "cliPath" | "model"> & {
  sessionFile?: string;
  providerOptions: PiRpcProviderOptions;
  enrichment?: PiEnrichmentConfig;
  runtimeMcpServers?: PiRuntimeMcpServers;
  mcpToolPolicies?: McpToolPolicy[];
  projectTrusted?: boolean;
  taskContext: TaskContext;
  extensions?: PiRuntimeExtension[];
  contextWikiPath?: string;
};

export function createPiRpcClient(options: PiRpcClientOptions): PiRpcClient {
  const {
    sessionFile,
    providerOptions,
    enrichment,
    runtimeMcpServers,
    mcpToolPolicies,
    projectTrusted,
    taskContext,
    extensions,
    contextWikiPath,
    ...rpcOptions
  } = options;
  const args = sessionFile ? ["--session-file", sessionFile] : [];
  const cliPath =
    rpcOptions.cliPath ??
    fileURLToPath(new URL("./rpc-host.js", import.meta.url));
  return new SecurePiRpcClient(
    {
      ...rpcOptions,
      cwd: taskContext.cwd,
      args,
      cliPath,
      provider: "posthog",
    },
    {
      providerOptions,
      enrichment,
      runtimeMcpServers,
      mcpToolPolicies,
      projectTrusted: projectTrusted ?? false,
      taskContext,
      extensions,
      contextWikiPath,
    } satisfies PiRpcBootstrap,
  );
}
