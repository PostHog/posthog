import { existsSync, readFileSync } from "node:fs";
import type { ImageContent } from "@earendil-works/pi-ai";
import {
  parseSessionEntries,
  type SessionEntry,
} from "@earendil-works/pi-coding-agent";
import { getRemotePiConversation } from "@posthog/agent/pi/remote-rpc-client";
import type { AgentRuntime, StoredLogEntry } from "@posthog/shared";
import type { StartPick } from "./chats";
import { sessionModel } from "./claudeLocal";
import { asEntry, type LocalAgent } from "./local";
import type { LocalChats } from "./localChats";
import { type PiControl, shortModelName } from "./models";
import type { AgentPrompt, PromptReply } from "./prompts";
import { emptyRunView, type RunView } from "./runs";
import { modesOf } from "./transcript";

const notStarted = (): Promise<never> =>
  Promise.reject(new Error("Send a message to start the agent first"));

// What a pane holds for a local chat for as long as it shows it: the saved conversation from disk until the first
// message starts the real agent, then that agent, through the same subscriptions, so the pane never starts over.
export class LocalChatHandle implements LocalAgent {
  private readonly cold: PiControl;
  private live: LocalAgent | null = null;
  private readonly viewers = new Map<(view: RunView) => void, () => void>();
  private readonly prompters = new Map<
    (prompts: AgentPrompt[]) => void,
    () => void
  >();

  constructor(
    private readonly saved: {
      runtime: AgentRuntime;
      plan: boolean;
      model: string | undefined;
      view: RunView;
    },
    // Starts the chat's agent, or returns the one already running.
    private readonly spawn: (pick?: StartPick) => Promise<LocalAgent>,
  ) {
    const { plan, model } = saved;
    const modes = modesOf(saved.view.entries);
    this.cold = {
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

  // What the files said the chat was on, until its agent says.
  get runtime(): AgentRuntime {
    return this.live?.runtime ?? this.saved.runtime;
  }
  get plan(): boolean {
    return this.live?.plan ?? this.saved.plan;
  }
  get model(): string | undefined {
    return this.live?.model ?? this.saved.model;
  }
  get control(): PiControl {
    return this.live?.control ?? this.cold;
  }

  // Hands the handle its running agent: every watcher moves over to it and keeps receiving.
  attach(agent: LocalAgent): void {
    if (this.live === agent) return;
    for (const stop of this.viewers.values()) stop();
    for (const stop of this.prompters.values()) stop();
    this.live = agent;
    for (const onView of this.viewers.keys())
      this.viewers.set(onView, agent.watch(onView));
    for (const onPrompts of this.prompters.keys())
      this.prompters.set(onPrompts, agent.watchPrompts(onPrompts));
  }

  async start(): Promise<void> {}

  watch(onView: (view: RunView) => void): () => void {
    this.viewers.set(
      onView,
      this.live ? this.live.watch(onView) : (onView(this.saved.view), () => {}),
    );
    return () => {
      this.viewers.get(onView)?.();
      this.viewers.delete(onView);
    };
  }

  async prompt(message: string, images?: ImageContent[]): Promise<void> {
    const agent = this.live ?? (await this.spawn());
    this.attach(agent);
    await agent.prompt(message, images);
  }

  watchPrompts(onPrompts: (prompts: AgentPrompt[]) => void): () => void {
    this.prompters.set(
      onPrompts,
      this.live ? this.live.watchPrompts(onPrompts) : () => {},
    );
    return () => {
      this.prompters.get(onPrompts)?.();
      this.prompters.delete(onPrompts);
    };
  }

  answer(prompt: AgentPrompt, reply: PromptReply): Promise<void> {
    return this.live ? this.live.answer(prompt, reply) : notStarted();
  }

  // The handle only shows the chat; stopping the agent is the hook's job.
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
  start: (pick?: StartPick) => Promise<LocalAgent>,
): Promise<LocalChatHandle | null> {
  const harness = chats.harnessOf(id);
  if (harness === "claude") {
    const entries = chats.acpLog(id).load().entries;
    const model = entries.reduce<string | undefined>(
      (found, entry) => sessionModel(entry) ?? found,
      undefined,
    );
    return new LocalChatHandle(
      { runtime: "acp", plan: true, model, view: coldView(entries) },
      start,
    );
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
  return new LocalChatHandle(
    {
      runtime: "pi",
      plan: lastModel !== null && lastModel.provider !== "posthog",
      model: lastModel?.modelId,
      view: coldView(history.map(asEntry)),
    },
    start,
  );
}
