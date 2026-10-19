import { existsSync, readFileSync } from "node:fs";
import {
  parseSessionEntries,
  type SessionEntry,
} from "@earendil-works/pi-coding-agent";
import { getRemotePiConversation } from "@posthog/agent/pi/remote-rpc-client";
import type { AgentRuntime, StoredLogEntry } from "@posthog/shared";
import { sessionModel } from "./claudeLocal";
import { asEntry, type LocalAgent } from "./local";
import type { LocalChats } from "./localChats";
import { type PiControl, shortModelName } from "./models";
import { emptyRunView, type RunView } from "./runs";
import { modesOf } from "./transcript";

const notStarted = (): Promise<never> =>
  Promise.reject(new Error("Send a message to start the agent first"));

// What a pane shows of a local chat before its agent runs: the saved conversation from its files on disk, and the
// model and plan it was on. The first message starts the real agent, which takes the pane over.
class ColdLocalAgent implements LocalAgent {
  readonly control: PiControl;

  constructor(
    readonly runtime: AgentRuntime,
    readonly plan: boolean,
    readonly model: string | undefined,
    private readonly view: RunView,
  ) {
    const modes = modesOf(view.entries);
    this.control = {
      models: async () => ({
        available: [],
        current: model
          ? {
              provider: plan ? "claude" : "posthog",
              id: model,
              name: shortModelName(model),
            }
          : null,
        effort: null,
      }),
      setModel: notStarted,
      efforts: async () => ({ available: [], current: null }),
      setEffort: notStarted,
      commands: async () => [],
      abort: async () => {},
      compact: notStarted,
      bash: notStarted,
      ...(modes && { modes: async () => modes, setMode: notStarted }),
    };
  }

  async start(): Promise<void> {}
  watch(onView: (view: RunView) => void): () => void {
    onView(this.view);
    return () => {};
  }
  prompt(): Promise<void> {
    return notStarted();
  }
  watchPrompts(): () => void {
    return () => {};
  }
  answer(): Promise<void> {
    return notStarted();
  }
  async stop(): Promise<void> {}
}

const coldView = (entries: StoredLogEntry[]): RunView => ({
  ...emptyRunView,
  loaded: true,
  local: true,
  entries,
});

// A local chat's saved conversation, read from its files on disk, so showing the chat never starts its agent.
export async function localHistory(
  chats: LocalChats,
  id: string,
): Promise<LocalAgent | null> {
  const harness = chats.harnessOf(id);
  if (harness === "claude") {
    const entries = chats.acpLog(id).load().entries;
    const model = entries.reduce<string | undefined>(
      (found, entry) => sessionModel(entry) ?? found,
      undefined,
    );
    return new ColdLocalAgent("acp", true, model, coldView(entries));
  }
  const file = chats.sessionFile(id);
  if (harness === null || !existsSync(file)) return null;
  // The same translation the running agent's entries get, over the file's entries in append order.
  const entries = parseSessionEntries(readFileSync(file, "utf8")).filter(
    (entry): entry is SessionEntry => entry.type !== "session",
  );
  const history = await getRemotePiConversation({
    getEntries: async () => ({ entries, leafId: null }),
  });
  // The model the chat was last switched to; one from the user's own ChatGPT login is on their plan, not PostHog's.
  const lastModel = entries.reduce<{
    provider: string;
    modelId: string;
  } | null>(
    (found, entry) =>
      entry.type === "model_change"
        ? (entry as unknown as { provider: string; modelId: string })
        : found,
    null,
  );
  return new ColdLocalAgent(
    "pi",
    lastModel !== null && lastModel.provider !== "posthog",
    lastModel?.modelId,
    coldView(history.map(asEntry)),
  );
}
