import type {
  AgentSideConnection,
  AvailableCommand,
  PromptRequest,
  PromptResponse,
} from "@agentclientprotocol/sdk";
import { visiblePromptBlocks } from "./prompt-blocks";

/**
 * What a session advertises for this command, so a client's command menu offers only what the
 * agent can honor. The adapter answers it rather than the model, like `/clear`, so no model
 * lists it and it has to be added to the declaration by hand.
 */
export const USAGE_AVAILABLE_COMMAND: AvailableCommand = {
  name: "usage",
  description:
    "Show PostHog AI credits for this conversation and billing period",
  input: null,
};

export function withUsageCommand<T extends { name: string }>(
  commands: T[],
  config: UsageCommandConfig | undefined,
): (T | AvailableCommand)[] {
  if (!config || commands.some((command) => command.name === "usage")) {
    return commands;
  }
  return [...commands, USAGE_AVAILABLE_COMMAND];
}

export interface UsageCommandConfig {
  /** PostHog renders the report, so no surface holds a second wording of it. */
  loadUsageMessage: () => Promise<string>;
}

export interface UsageSource {
  getAiUsageMessage(args: {
    conversationId?: string;
    conversationStartedAt?: string;
    product?: string;
  }): Promise<string>;
}

/** The desktop app's own runs are billed as PostHog Desktop. */
const LOCAL_AI_PRODUCT = "posthog_code";

export function usageCommandConfig(
  source: UsageSource | undefined,
  conversationId: string | undefined,
  conversationStartedAt: string | undefined,
  product: string = LOCAL_AI_PRODUCT,
): UsageCommandConfig | undefined {
  if (!source) return undefined;
  return {
    loadUsageMessage: () =>
      source.getAiUsageMessage({
        conversationId,
        conversationStartedAt,
        product,
      }),
  };
}

/**
 * One `<posthog_context>` / `<posthog_trusted_context>` / `<posthog_untrusted_context>` block.
 * The PostHog AI composer prefixes the resources a person is looking at as these blocks, so the
 * command they typed sits after them and an exact match on the whole text would miss it.
 */
const CONTEXT_BLOCK =
  /^\s*<posthog_(trusted_|untrusted_)?context>[\s\S]*?<\/posthog_\1context>\s*/;

function typedCommand(text: string): string {
  let rest = text;
  for (let stripped = rest.replace(CONTEXT_BLOCK, ""); stripped !== rest; ) {
    rest = stripped;
    stripped = rest.replace(CONTEXT_BLOCK, "");
  }
  return rest.trim().toLowerCase();
}

export function isUsageCommand(params: PromptRequest): boolean {
  const visible = visiblePromptBlocks(params.prompt);
  return (
    visible.length === 1 &&
    visible[0]?.type === "text" &&
    typedCommand(visible[0].text) === "/usage"
  );
}

export async function handleUsageCommand({
  client,
  sessionId,
  params,
  config,
}: {
  client: AgentSideConnection;
  sessionId: string;
  params: PromptRequest;
  config: UsageCommandConfig;
}): Promise<PromptResponse> {
  for (const block of visiblePromptBlocks(params.prompt)) {
    if (block.type !== "text" && block.type !== "image") continue;
    await client.sessionUpdate({
      sessionId,
      update: {
        sessionUpdate: "user_message_chunk",
        content: block,
      },
    });
  }

  let message: string;
  try {
    message = await config.loadUsageMessage();
  } catch {
    message = "Couldn't load PostHog AI usage. Try again in a moment.";
  }
  await client.sessionUpdate({
    sessionId,
    update: {
      sessionUpdate: "agent_message_chunk",
      content: { type: "text", text: message },
    },
  });
  return { stopReason: "end_turn" };
}
