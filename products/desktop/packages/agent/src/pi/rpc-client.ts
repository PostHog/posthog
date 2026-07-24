import { type ChildProcess, spawn } from "node:child_process";
import type { Writable } from "node:stream";
import { StringDecoder } from "node:string_decoder";
import { fileURLToPath } from "node:url";
import {
  type Api,
  getSupportedThinkingLevels,
  type Model,
} from "@earendil-works/pi-ai";
import {
  RpcClient,
  type RpcClientOptions,
} from "@earendil-works/pi-coding-agent";
import { safePiEnvironment } from "./rpc-environment";
import type { PiModelOption, PiThinkingLevel } from "./types";

export type PiRpcClient = RpcClient;

export interface PiRpcProviderOptions {
  region?: "us" | "eu" | "dev";
  apiKey: string;
  baseUrl?: string;
}

export async function getAvailableModelsWithThinkingLevels(
  client: PiRpcClient,
): Promise<PiModelOption[]> {
  const models = await client.getAvailableModels();

  return models.map((model) => ({
    ...model,
    thinkingLevels: getSupportedThinkingLevels(
      model as unknown as Model<Api>,
    ) as PiThinkingLevel[],
  }));
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
  constructor(
    private readonly secureOptions: RpcClientOptions,
    private readonly providerOptions: PiRpcProviderOptions,
  ) {
    super(secureOptions);
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
        env: safePiEnvironment(process.env),
        stdio: ["pipe", "pipe", "pipe", "pipe"],
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
    bootstrapPipe?.end(
      JSON.stringify({ providerOptions: this.providerOptions }),
    );

    await new Promise((resolve) => setTimeout(resolve, 100));
    if (child.exitCode !== null) {
      throw (
        internals.exitError ??
        internals.createProcessExitError(child.exitCode, child.signalCode)
      );
    }
  }
}

export function getPiRpcClientProcess(
  client: PiRpcClient,
): ChildProcess | null {
  return (client as unknown as RpcClientProcessAccess).process ?? null;
}

export type PiRpcClientOptions = Pick<RpcClientOptions, "cwd" | "model"> & {
  sessionFile?: string;
  providerOptions: PiRpcProviderOptions;
};

export function createPiRpcClient(options: PiRpcClientOptions): PiRpcClient {
  const { sessionFile, providerOptions, ...rpcOptions } = options;
  const args = sessionFile ? ["--session-file", sessionFile] : [];
  return new SecurePiRpcClient(
    {
      ...rpcOptions,
      args,
      cliPath: fileURLToPath(new URL("./rpc-host.js", import.meta.url)),
      provider: "posthog",
    },
    providerOptions,
  );
}
