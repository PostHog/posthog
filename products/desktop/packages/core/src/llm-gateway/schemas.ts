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

export type PromptInput = z.infer<typeof promptInput>;

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
  detail?: unknown;
}

export type { UsageBucket, UsageOutput } from "../usage/schemas";
export {
  usageBucketSchema,
  usageOutput,
} from "../usage/schemas";
