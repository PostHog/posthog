import type {
  AgentSideConnection,
  PromptRequest,
  PromptResponse,
} from "@agentclientprotocol/sdk";
import { visiblePromptBlocks } from "./prompt-blocks";

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

export function isUsageCommand(params: PromptRequest): boolean {
  const visible = visiblePromptBlocks(params.prompt);
  return (
    visible.length === 1 &&
    visible[0]?.type === "text" &&
    visible[0].text.trim().toLowerCase() === "/usage"
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
