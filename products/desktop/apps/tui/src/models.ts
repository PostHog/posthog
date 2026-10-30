import {
  type PiRemoteRpcClient,
  RemotePiRpcClient,
} from "@posthog/agent/pi/remote-rpc-client";
import { SESSION_START_MODEL_ID } from "@posthog/harness/extensions/posthog-provider/model-catalog";
import { isOfferedModel } from "@posthog/shared/model-catalog";
import { CHATGPT_PROVIDER } from "./chatgpt";
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

// pi's thinking level: how much the model reasons before it answers.
export type Effort = Parameters<PiRemoteRpcClient["setThinkingLevel"]>[0];

export interface PiControl {
  // The models on offer, and the model and effort the run is on now.
  models(): Promise<{
    available: ModelChoice[];
    current: ModelChoice | null;
    effort: Effort | null;
  }>;
  setModel(model: ModelChoice): Promise<void>;
  // The efforts the run's current model supports, and the one it is on.
  efforts(): Promise<{ available: Effort[]; current: Effort | null }>;
  // pi moves an effort the model does not support to the nearest one it does.
  setEffort(effort: Effort): Promise<void>;
  // The run's own slash commands: extension commands, prompt templates and skills.
  commands(): Promise<RunCommand[]>;
  // Stops the agent's current turn.
  abort(): Promise<void>;
  // Summarises older messages to free up context, focused by the instructions if given.
  compact(instructions?: string): Promise<Compaction>;
  // Runs a command where the agent runs and adds its output to the agent's context, like ! in pi.
  bash(command: string): Promise<ShellResult>;
  // Claude Code's permission modes (plan, auto, ...), on a chat that has them.
  modes?: () => Promise<{ available: Mode[]; current: string }>;
  setMode?: (id: string) => Promise<void>;
}

export interface Mode {
  id: string;
  name: string;
}

export interface Compaction {
  tokensBefore: number;
  // pi's estimate over the rebuilt context, not a provider's count.
  estimatedTokensAfter?: number;
}

export interface RunCommand {
  name: string;
  description?: string;
}

// The TUI runs on the PostHog harness. Pi also reports models from the user's
// own pi logins (~/.pi/agent/auth.json), and picking one leaves the gateway, so
// only the ChatGPT login from settings gets through. The gateway also serves
// models the shared catalog does not offer, which the desktop picker hides too.
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

// TUI chats pin no model and pi tasks take no saved defaults, so cloud and local runs both start here.
export const STARTING_MODEL = choice({
  provider: HARNESS_PROVIDER,
  id: SESSION_START_MODEL_ID,
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
    | "getAvailableModels"
    | "getState"
    | "setModel"
    | "getAvailableThinkingLevels"
    | "setThinkingLevel"
    | "getCommands"
    | "abort"
    | "compact"
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
              (model.provider === HARNESS_PROVIDER &&
                isOfferedModel(model.id)) ||
              model.provider === CHATGPT_PROVIDER,
          )
          .map(choice),
        current: state.model ? choice(state.model) : null,
        effort: state.thinkingLevel ?? null,
      };
    },
    setModel: async (model) => {
      await client.setModel(model.provider, model.id);
    },
    efforts: async () => {
      const [available, state] = await Promise.all([
        client.getAvailableThinkingLevels(),
        client.getState(),
      ]);
      return { available, current: state.thinkingLevel ?? null };
    },
    setEffort: (effort) => client.setThinkingLevel(effort),
    abort: () => client.abort(),
    compact: async (instructions) => {
      const { tokensBefore, estimatedTokensAfter } =
        await client.compact(instructions);
      return { tokensBefore, estimatedTokensAfter };
    },
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

// The same words the desktop app uses for pi's levels.
export const EFFORT_LABELS: Record<Effort, string> = {
  off: "Off",
  minimal: "Minimal",
  low: "Low",
  medium: "Medium",
  high: "High",
  xhigh: "Extra high",
  max: "Max",
};

// "Opus 5.5 (high)": the effort qualifies the model, as pi's own footer shows it.
export function modelWithEffort(
  model: string | undefined,
  effort: Effort | undefined,
): string | undefined {
  if (!effort) return model;
  const level =
    effort === "off" ? "thinking off" : EFFORT_LABELS[effort].toLowerCase();
  return model ? `${model} (${level})` : level;
}

export function modeSheet(available: Mode[], current: string): Sheet {
  return {
    title: "Select mode",
    description:
      "Switches this chat's permission mode now, and for new Claude Code chats.",
    items: available.map((mode) => ({
      label: mode.name,
      current: mode.id === current,
    })),
    footer: "Enter to select · Esc to cancel",
  };
}

export function effortSheet(
  available: Effort[],
  current: Effort | null,
  description: string,
): Sheet {
  return {
    title: "Select effort",
    description,
    items: available.map((effort) => ({
      label: EFFORT_LABELS[effort],
      current: effort === current,
    })),
    footer: "Enter to select · Esc to cancel",
  };
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
