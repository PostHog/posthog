import { createHash } from "node:crypto";
import type { AgentMessage } from "@earendil-works/pi-agent-core";
import type {
  ExtensionFactory,
  SessionManager,
} from "@earendil-works/pi-coding-agent";
import { PostHogAPIClient } from "../posthog-api";
import {
  type ContextDelivery,
  ContextSelection,
} from "../server/context-selection";
import { readPersistedPiQueue } from "./queue-persistence";

export interface PiContextSelectionConfig {
  apiUrl: string;
  apiKey: string;
  projectId: number;
  runId: string;
  runtimeVersion: string;
}

interface PiContextInput {
  format: "pi_context";
  messages: AgentMessage[];
  system_prompt: string;
  model: { id: string; provider: string } | null;
}

function hash(value: unknown): string {
  return createHash("sha256").update(JSON.stringify(value)).digest("hex");
}

function messageText(message: AgentMessage): string {
  if (!("content" in message)) return "";
  if (typeof message.content === "string") return message.content;
  return message.content
    .flatMap((part) => (part.type === "text" ? [part.text] : []))
    .join("");
}

/** Runs at Pi's model boundary, after queued human messages leave the native queue. */
export class PiContextSelection {
  readonly extension: { name: string; factory: ExtensionFactory };
  private pending: { id: string; hash: string }[] = [];
  // Pi messages have no request ID, so uncertain text stays excluded for this process.
  private readonly blocked = new Set<string>();
  private readonly exposed = new Map<string, AgentMessage | null>();
  private active:
    | {
        key: string;
        turnIndex: number | undefined;
        delivery: ContextDelivery<PiContextInput>;
      }
    | undefined;
  private currentTurnIndex: number | undefined;

  constructor(
    config: PiContextSelectionConfig,
    sessions: Pick<SessionManager, "getEntries" | "appendCustomEntry">,
    api = new PostHogAPIClient({
      apiUrl: config.apiUrl,
      projectId: config.projectId,
      getApiKey: () => config.apiKey,
      userAgent: "posthog/pi-context-selection",
    }),
    report: (event: Record<string, unknown>) => void = (event) => {
      try {
        sessions.appendCustomEntry(
          "posthog-context-selection-diagnostic",
          event,
        );
      } catch {
        process.stderr.write(`context_selection ${JSON.stringify(event)}\n`);
      }
    },
  ) {
    for (const text of readPersistedPiQueue(sessions.getEntries()).followUp)
      this.blocked.add(hash(text));
    const selector = new ContextSelection(api, report, config.runtimeVersion);
    selector.enabled = true;
    this.extension = {
      name: "posthog-context-selection",
      factory: (pi) => {
        pi.on("agent_start", async () => {
          this.currentTurnIndex = undefined;
        });
        pi.on("turn_start", async (event) => {
          this.currentTurnIndex = event.turnIndex;
        });
        pi.on("context", async (event, ctx) => {
          try {
            const latest = event.messages.findLast(
              (message) => message.role === "user",
            );
            if (!latest) return;
            const latestHash = hash(latest);
            const key = `${latestHash}:${event.messages.filter((message) => message.role === "user" && hash(message) === latestHash).length}`;
            const userText = messageText(latest);
            const fresh = !this.exposed.has(key);
            if (fresh) {
              const previous = this.active;
              if (previous && previous.key !== key) {
                this.active = undefined;
                await previous.delivery.finish(
                  { stopReason: "superseded" },
                  true,
                );
              }
              this.exposed.set(key, null);
            }
            const index = this.blocked.has(hash(userText))
              ? -1
              : this.pending.findIndex(
                  (input) => input.hash === hash(userText),
                );
            if (index >= 0 && fresh) {
              const [input] = this.pending.splice(index, 1);
              const history = event.messages
                .slice(0, event.messages.lastIndexOf(latest))
                .filter(
                  (message) =>
                    message.role === "user" || message.role === "assistant",
                )
                .map((message) => `${message.role}: ${messageText(message)}`)
                .join("\n")
                .slice(-12_000);
              const baseline = this.withExposures(event.messages);
              const delivery = await selector.preparePrompt<PiContextInput>({
                runId: config.runId,
                messageId: input.id,
                prompt: {
                  format: "pi_context",
                  messages: baseline,
                  system_prompt: ctx.getSystemPrompt(),
                  model: ctx.model
                    ? { id: ctx.model.id, provider: ctx.model.provider }
                    : null,
                },
                userText,
                restoredHistory: history,
                historySource: "runtime",
                inject: (input, context) => ({
                  ...input,
                  messages: [
                    ...input.messages,
                    {
                      role: "custom",
                      customType: "posthog_context_selection",
                      content: context,
                      display: false,
                      timestamp: latest.timestamp,
                    },
                  ],
                }),
              });
              this.active = {
                key,
                turnIndex: this.currentTurnIndex,
                delivery,
              };
              const injected =
                delivery.prompt.messages.length > baseline.length
                  ? delivery.prompt.messages.at(-1)
                  : undefined;
              if (injected) this.exposed.set(key, injected);
              return { messages: delivery.prompt.messages };
            }
            return { messages: this.withExposures(event.messages) };
          } catch (error) {
            report({
              event: "pi_context_failed",
              error_type: error instanceof Error ? error.name : "unknown",
            });
            return { messages: event.messages };
          }
        });
        pi.on("turn_end", async (event) => {
          if (
            this.active?.turnIndex !== undefined &&
            this.active.turnIndex !== event.turnIndex
          )
            return;
          const delivery = this.active?.delivery;
          this.active = undefined;
          if (!delivery || event.message.role !== "assistant") return;
          const message = event.message;
          await delivery.finish(
            {
              stopReason: message.stopReason,
              usage: {
                scope: "pi_model_turn",
                model: message.model,
                provider: message.provider,
                ...message.usage,
              },
            },
            message.stopReason === "error" || message.stopReason === "aborted",
          );
        });
        pi.on("agent_settled", async () => {
          if (!this.active) return;
          const delivery = this.active.delivery;
          this.active = undefined;
          await delivery.finish(
            { stopReason: "settled_without_model_result" },
            true,
          );
        });
      },
    };
  }

  register(id: string, text: string): void {
    if (text.startsWith("/")) return;
    const fingerprint = hash(text);
    const previous = this.pending.find((input) => input.id === id);
    if (previous && previous.hash !== fingerprint)
      this.blocked.add(previous.hash);
    this.pending = this.pending.filter((input) => input.id !== id);
    if (this.blocked.has(fingerprint)) return;
    if (this.pending.some((input) => input.hash === fingerprint)) {
      this.blocked.add(fingerprint);
      this.pending = this.pending.filter((input) => input.hash !== fingerprint);
      return;
    }
    if (this.pending.length === 128) {
      const dropped = this.pending.shift();
      if (dropped) this.blocked.add(dropped.hash);
    }
    this.pending.push({ id, hash: fingerprint });
  }

  unregister(id: string): void {
    for (const input of this.pending)
      if (input.id === id) this.blocked.add(input.hash);
    this.pending = this.pending.filter((input) => input.id !== id);
  }

  clearPending(): void {
    for (const input of this.pending) this.blocked.add(input.hash);
    this.pending = [];
  }

  blockText(text: string): void {
    const fingerprint = hash(text);
    this.blocked.add(fingerprint);
    this.pending = this.pending.filter((input) => input.hash !== fingerprint);
  }

  private withExposures(messages: AgentMessage[]): AgentMessage[] {
    const occurrences = new Map<string, number>();
    return messages.flatMap((message) => {
      const fingerprint = hash(message);
      const occurrence = (occurrences.get(fingerprint) ?? 0) + 1;
      occurrences.set(fingerprint, occurrence);
      const exposure =
        message.role === "user"
          ? this.exposed.get(`${fingerprint}:${occurrence}`)
          : undefined;
      return exposure && messageText(exposure)
        ? [message, exposure]
        : [message];
    });
  }
}
