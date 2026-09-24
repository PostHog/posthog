import { z } from "zod";

export const llmMessageSchema = z.object({
  role: z.enum(["user", "assistant"]),
  content: z.string(),
});

export type LlmMessage = z.infer<typeof llmMessageSchema>;

export const promptInput = z.object({
  system: z.string().optional(),
  messages: z.array(llmMessageSchema),
  maxTokens: z.number().optional(),
  model: z.string().optional(),
});

export const promptOutput = z.object({
  content: z.string(),
  model: z.string(),
  stopReason: z.string().nullable(),
  usage: z.object({
    inputTokens: z.number(),
    outputTokens: z.number(),
  }),
});

export type PromptOutput = z.infer<typeof promptOutput>;

export interface AnthropicMessagesRequest {
  model: string;
  messages: Array<{ role: "user" | "assistant"; content: string }>;
  max_tokens?: number;
  system?: string;
  stream?: boolean;
}

export interface AnthropicMessagesResponse {
  id: string;
  type: "message";
  role: "assistant";
  content: Array<{ type: "text"; text: string }>;
  model: string;
  stop_reason: string | null;
  usage: {
    input_tokens: number;
    output_tokens: number;
  };
}

export interface AnthropicErrorResponse {
  error?: {
    message: string;
    type: string;
    code?: string;
  };
  /** The Go gateway's flat envelope. */
  code?: unknown;
  message?: unknown;
  detail?: unknown;
}

export const gatewayTokenMintedSchema = z.object({
  enabled: z.literal(true),
  token: z.string().startsWith("phe_"),
  expires_at: z.string(),
  cap_usd: z.string(),
  gateway_url: z.string(),
  product: z.string(),
  team_id: z.number(),
  plan: z.enum(["paid", "free"]),
  allowed_models: z.array(z.string()),
  product_models: z.array(z.string()),
});
export type GatewayTokenMinted = z.infer<typeof gatewayTokenMintedSchema>;

export const gatewayTokenRefusalSchema = z.object({
  enabled: z.literal(false).optional(),
  reason: z.string().optional(),
  /** DRF permission refusals carry the reason here instead. */
  code: z.string().optional(),
  detail: z.string().optional(),
  access: z.unknown().optional(),
});

export type GatewayRoute =
  | { mode: "legacy"; reason: string }
  | {
      mode: "blocked";
      reason: "credit_bucket_exhausted";
      detail: string;
    }
  | {
      mode: "go";
      gatewayUrl: string;
      token: string;
      /** Epoch ms. */
      expiresAt: number;
      capUsd: string;
      allowedModels: string[] | null;
      productModels: string[];
      plan: "paid" | "free";
      projectId: number;
      teamId: number;
      source: "mint" | "override";
    };

export type GatewayRemintReason = "unauthorized" | "token_cap_exceeded";

export type { UsageOutput } from "../usage/schemas";
export { usageOutput } from "../usage/schemas";
