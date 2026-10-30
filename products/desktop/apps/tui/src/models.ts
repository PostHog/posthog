import {
  type PiRemoteRpcClient,
  RemotePiRpcClient,
} from "@posthog/agent/pi/remote-rpc-client";
import { isOfferedModel } from "@posthog/shared/model-catalog";
import type { Sheet } from "./sheet";
import type { ShellResult } from "./shell";

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
  // The run's own slash commands: extension commands, prompt templates and skills.
  commands(): Promise<RunCommand[]>;
  // Stops the agent's current turn.
  abort(): Promise<void>;
  // Runs a command where the agent runs and adds its output to the agent's context, like ! in pi.
  bash(command: string): Promise<ShellResult>;
}

export interface RunCommand {
  name: string;
  description?: string;
}

// The TUI runs only on the PostHog harness. Pi also reports models from the
// user's own pi logins (~/.pi/agent/auth.json), and picking one leaves the
// gateway, so those stay out of the picker. The gateway also serves models the
// shared catalog does not offer, which the desktop picker hides too.
const HARNESS_PROVIDER = "posthog";

const BRAND_NAMES: Record<string, string> = {
  claude: "Claude",
  deepseek: "DeepSeek",
  gemini: "Gemini",
  glm: "GLM",
  gpt: "GPT",
  kimi: "Kimi",
};

// These vendors give each model line its own name (Opus, Astra), so the
// brand adds nothing. Gemini and the open models do not, so they keep it.
const NAMED_LINE_BRANDS = new Set(["claude", "gpt"]);

// Words that qualify a model rather than name its line.
const QUALIFIERS = new Set(["flash", "lite", "mini", "nano", "preview", "pro"]);

const VERSION_PART = /^[kv]?(\d{1,3}(?:\.\d+)?)$/;

const titleCase = (word: string): string =>
  word.charAt(0).toUpperCase() + word.slice(1);

// "claude-opus-5-5" reads "Opus 5.5", "gpt-6.1-sol" "Sol 6.1",
// "gemini-3-pro-preview-06-05" "Gemini 3 Pro Preview", "moonshotai/kimi-k3" "Kimi 3".
export function shortModelName(id: string): string {
  const [brand, ...rest] = (id.split("/").pop() ?? id).toLowerCase().split("-");
  const version: string[] = [];
  const words: string[] = [];
  // Only the first run of numbers is the version. Claude puts it after the
  // line (claude-opus-5-5); numbers after a later word are a release date.
  let versionEnded = false;
  for (const token of rest) {
    const part = VERSION_PART.exec(token);
    if (part && !versionEnded) {
      version.push(part[1]);
    } else if (!/^\d+$/.test(token)) {
      words.push(titleCase(token));
      versionEnded = version.length > 0;
    }
  }
  const versionText = version.join(".");
  const lineFirst =
    NAMED_LINE_BRANDS.has(brand) &&
    words.length > 0 &&
    !QUALIFIERS.has(words[0].toLowerCase());
  const parts = lineFirst
    ? [words[0], versionText, ...words.slice(1)]
    : [BRAND_NAMES[brand] ?? titleCase(brand), versionText, ...words];
  return parts.filter(Boolean).join(" ");
}

const choice = (model: { provider: string; id: string }): ModelChoice => ({
  provider: model.provider,
  id: model.id,
  name: shortModelName(model.id),
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
  return controlOf(client, (command) => client.bash(command));
}

// The same model, command and stop controls over any pi RPC client, cloud or local.
export function controlOf(
  client: Pick<
    PiRemoteRpcClient,
    "getAvailableModels" | "getState" | "setModel" | "getCommands" | "abort"
  >,
  // The local client sends bash through the runtime, which the remote client's interface does not cover.
  bash: PiControl["bash"],
): PiControl {
  return {
    models: async () => {
      const [available, state] = await Promise.all([
        client.getAvailableModels(),
        client.getState(),
      ]);
      return {
        available: available
          .filter(
            (model) =>
              model.provider === HARNESS_PROVIDER && isOfferedModel(model.id),
          )
          .map(choice),
        current: state.model ? choice(state.model) : null,
      };
    },
    setModel: async (model) => {
      await client.setModel(model.provider, model.id);
    },
    abort: () => client.abort(),
    bash,
    commands: async () =>
      (await client.getCommands()).map(({ name, description }) => ({
        name,
        description,
      })),
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
