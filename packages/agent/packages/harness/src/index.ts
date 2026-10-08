import type { AgentSessionRuntime } from "@earendil-works/pi-coding-agent";

export {
  type PosthogOAuthCredentials,
  parsePosthogOAuthCredentials,
  setPosthogOAuthCredentials,
} from "./extensions/posthog-provider/provider";
export {
  createHarnessRuntime,
  type HarnessRuntimeOptions,
} from "./runtime";

/** Run a harness runtime using Pi's native JSONL RPC protocol. */
export async function runRpcMode(runtime: AgentSessionRuntime): Promise<never> {
  const pi = await import("@earendil-works/pi-coding-agent");
  return pi.runRpcMode(runtime);
}

export type {
  AgentSession,
  AgentSessionEvent,
  AgentSessionRuntime,
  RpcCommand,
  RpcExtensionUIRequest,
  RpcExtensionUIResponse,
  RpcResponse,
  RpcSessionState,
} from "@earendil-works/pi-coding-agent";
