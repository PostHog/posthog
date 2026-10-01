import { createHash } from "node:crypto";
import type { AgentMessage } from "@earendil-works/pi-agent-core";
import type {
  ExtensionFactory,
  SessionManager,
} from "@earendil-works/pi-coding-agent";
import { z } from "zod/v4";
import { PostHogAPIClient } from "../posthog-api";
import {
  type ContextDelivery,
  ContextSelection,
} from "../server/context-selection";

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

const ENTRY_TYPE = "posthog-context-selection-inputs";
const pendingSchema = z
  .array(z.object({ id: z.string(), hash: z.string() }))
  .max(128);

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
  private pending: z.infer<typeof pendingSchema> = [];
  private readonly exposed = new Map<string, AgentMessage | null>();
  private active: ContextDelivery<PiContextInput> | undefined;

  constructor(
    config: PiContextSelectionConfig,
    private readonly sessions: Pick<
      SessionManager,
      "getEntries" | "appendCustomEntry"
    >,
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
    const saved = sessions
      .getEntries()
      .findLast(
        (entry) => entry.type === "custom" && entry.customType === ENTRY_TYPE,
      );
    const parsed = pendingSchema.safeParse(
      saved?.type === "custom" ? saved.data : undefined,
    );
    if (parsed.success) this.pending = parsed.data;
    const selector = new ContextSelection(api, report, config.runtimeVersion);
    selector.enabled = true;
    this.extension = {
      name: "posthog-context-selection",
      factory: (pi) => {
        pi.on("context", async (event, ctx) => {
          try {
            const latest = event.messages.findLast(
              (message) => message.role === "user",
            );
            if (!latest) return;
            const latestHash = hash(latest);
            const key = `${latestHash}:${event.messages.filter((message) => message.role === "user" && hash(message) === latestHash).length}`;
            const userText = messageText(latest);
            const index = this.pending.findIndex(
              (input) => input.hash === hash(userText),
            );
            if (index >= 0 && !this.exposed.has(key)) {
              const [input] = this.pending.splice(index, 1);
              this.persistPending();
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
              this.active = delivery;
              const injected =
                delivery.prompt.messages.length > baseline.length
                  ? delivery.prompt.messages.at(-1)
                  : undefined;
              if (injected) this.exposed.set(key, injected);
              // Remember even control and failed preparations so a model retry cannot consume another equal queued prompt.
              else this.exposed.set(key, null);
              const oldest = this.exposed.keys().next().value;
              if (this.exposed.size > 128 && oldest)
                this.exposed.delete(oldest);
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
          const delivery = this.active;
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
          const delivery = this.active;
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
    this.pending = this.pending.filter((input) => input.id !== id);
    this.pending.push({ id, hash: hash(text) });
    this.pending = this.pending.slice(-128);
    this.persistPending();
  }

  unregister(id: string): void {
    this.pending = this.pending.filter((input) => input.id !== id);
    this.persistPending();
  }

  clearPending(): void {
    this.pending = [];
    this.persistPending();
  }

  private persistPending(): void {
    this.sessions.appendCustomEntry(ENTRY_TYPE, this.pending);
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
