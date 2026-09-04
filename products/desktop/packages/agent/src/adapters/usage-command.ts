import type {
  AgentSideConnection,
  PromptRequest,
  PromptResponse,
} from "@agentclientprotocol/sdk";
import { visiblePromptBlocks } from "./prompt-blocks";

export interface UsageCommandConfig {
  url: string;
  authToken: string;
  projectId?: string;
}

interface UsageResponse {
  ai_credits?: {
    exhausted: boolean;
    used_usd?: number | null;
    limit_usd?: number | null;
  };
  billing_period_end?: string | null;
}

function isUsageResponse(value: unknown): value is UsageResponse {
  if (typeof value !== "object" || value === null) return false;
  const credits = (value as UsageResponse).ai_credits;
  return (
    credits === undefined ||
    (typeof credits === "object" &&
      credits !== null &&
      typeof credits.exhausted === "boolean")
  );
}

export function isUsageCommand(params: PromptRequest): boolean {
  const visible = visiblePromptBlocks(params.prompt);
  return (
    visible.length === 1 &&
    visible[0]?.type === "text" &&
    visible[0].text.trim().toLowerCase() === "/usage"
  );
}

function creditsFromUsd(value: number): number {
  return Math.round(value * 100);
}

function formatCredits(value: number): string {
  return value.toLocaleString("en-US");
}

export function formatUsageResponse(usage: UsageResponse): string {
  const credits = usage.ai_credits;
  if (!credits) {
    return "PostHog AI usage is unavailable. Try again in a moment.";
  }

  const lines = ["## PostHog AI usage", ""];
  if (credits.used_usd != null && credits.limit_usd != null) {
    const used = creditsFromUsd(credits.used_usd);
    const limit = creditsFromUsd(credits.limit_usd);
    lines.push(
      `**Billing period**: ${formatCredits(used)} of ${formatCredits(limit)} credits`,
    );
    lines.push(
      `**Remaining**: ${formatCredits(Math.max(0, limit - used))} credits`,
    );
  } else if (credits.used_usd != null) {
    lines.push(
      `**Billing period**: ${formatCredits(creditsFromUsd(credits.used_usd))} credits used`,
    );
  } else {
    lines.push("Billing period usage is not available yet.");
  }

  lines.push(
    `**Status**: ${credits.exhausted ? "Credit limit reached" : "Credits available"}`,
  );
  if (usage.billing_period_end) {
    const resetAt = new Date(usage.billing_period_end);
    if (!Number.isNaN(resetAt.getTime())) {
      lines.push(`**Resets**: ${resetAt.toISOString().slice(0, 10)}`);
    }
  }
  lines.push("", "_Usage data may take a few minutes to update._");
  return lines.join("\n");
}

async function fetchUsage(config: UsageCommandConfig): Promise<UsageResponse> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${config.authToken}`,
  };
  if (config.projectId) {
    headers["X-PostHog-Project-Id"] = config.projectId;
  }
  const response = await fetch(config.url, { headers });
  if (!response.ok) {
    throw new Error(`Usage request failed with status ${response.status}`);
  }
  const body: unknown = await response.json();
  if (!isUsageResponse(body)) {
    throw new Error("Usage response did not match the expected shape");
  }
  return body;
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
    message = formatUsageResponse(await fetchUsage(config));
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
