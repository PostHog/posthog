import { RemotePiRpcClient } from "@posthog/agent/pi/remote-rpc-client";
import type { Sheet } from "./sheet";

export interface ModelChoice {
  provider: string;
  id: string;
  name: string;
}

// Sends a pi RPC to one run's sandbox; the caller fills in the host and project.
export type PiCommand = (input: {
  taskId: string;
  runId: string;
  id?: string;
  method: "pi/rpc";
  params: { command: unknown };
}) => Promise<{ success: boolean; result?: unknown; error?: string }>;

export interface PiControl {
  models(): Promise<{ available: ModelChoice[]; current: ModelChoice | null }>;
  setModel(model: ModelChoice): Promise<void>;
}

const choice = (model: {
  provider: string;
  id: string;
  name?: string;
}): ModelChoice => ({
  provider: model.provider,
  id: model.id,
  name: model.name ?? model.id,
});

// The live run's own pi session, reached the same way the desktop app reaches it.
export function piControl(
  send: PiCommand,
  taskId: string,
  runId: string,
): PiControl {
  const client = new RemotePiRpcClient({
    request: async (command) => {
      const response = await send({
        taskId,
        runId,
        id: command.id,
        method: "pi/rpc",
        params: { command },
      });
      if (!response.success)
        throw new Error(response.error ?? `Pi command failed: ${command.type}`);
      return response.result;
    },
  });
  return {
    models: async () => {
      const [available, state] = await Promise.all([
        client.getAvailableModels(),
        client.getState(),
      ]);
      return {
        available: available.map(choice),
        current: state.model ? choice(state.model) : null,
      };
    },
    setModel: async (model) => {
      await client.setModel(model.provider, model.id);
    },
  };
}

export function parseSlash(
  text: string,
): { command: string; args: string } | null {
  const match = /^\/(\S+)\s*(.*)$/.exec(text.trim());
  return match ? { command: match[1], args: match[2] } : null;
}

export function modelSheet(
  available: ModelChoice[],
  current: ModelChoice | null,
  description: string,
): Sheet {
  return {
    title: "Select model",
    description,
    items: available.map((model) => ({
      label: model.name,
      current: current?.provider === model.provider && current.id === model.id,
    })),
    footer: "Enter to select · Esc to cancel",
  };
}
