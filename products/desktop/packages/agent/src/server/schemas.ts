import { z } from "zod/v4";

export { posthogExecPermissionRegexSchema } from "../posthog-exec-permission";

const httpHeaderSchema = z.object({
  name: z.string(),
  value: z.string(),
});

const nullishString = z
  .string()
  .nullish()
  .transform((value) => value ?? null);

export const handoffLocalGitStateSchema = z.object({
  head: nullishString,
  branch: nullishString,
  upstreamHead: nullishString,
  upstreamRemote: nullishString,
  upstreamMergeRef: nullishString,
});

const remoteMcpServerSchema = z.object({
  type: z.enum(["http", "sse"]),
  name: z.string().min(1, "MCP server name is required"),
  url: z.url({ error: "MCP server url must be a valid URL" }),
  headers: z.array(httpHeaderSchema).default([]),
});

export const mcpServersSchema = z.array(remoteMcpServerSchema);

export type RemoteMcpServer = z.infer<typeof remoteMcpServerSchema>;

export const claudeCodeConfigSchema = z.object({
  systemPrompt: z
    .union([
      z.string(),
      z.object({
        type: z.literal("preset"),
        preset: z.literal("claude_code"),
        append: z.string().optional(),
      }),
    ])
    .optional(),
  plugins: z
    .array(z.object({ type: z.literal("local"), path: z.string() }))
    .optional(),
});

export const jsonRpcRequestSchema = z.object({
  jsonrpc: z.literal("2.0"),
  method: z.string(),
  params: z.record(z.string(), z.unknown()).optional(),
  id: z.union([z.string(), z.number()]).optional(),
});

export type JsonRpcRequest = z.infer<typeof jsonRpcRequestSchema>;

export const userMessageParamsSchema = z
  .object({
    content: z
      .union([
        z.string().min(1, "Content is required"),
        z
          .array(z.record(z.string(), z.unknown()))
          .min(1, "Content is required"),
      ])
      .optional(),
    artifacts: z.array(z.record(z.string(), z.unknown())).optional(),
    messageId: z.string().min(1).optional(),
    steer: z.boolean().optional(),
  })
  .refine(
    (params) => {
      const hasContent =
        typeof params.content === "string"
          ? params.content.trim().length > 0
          : Array.isArray(params.content) && params.content.length > 0;
      const hasArtifacts =
        Array.isArray(params.artifacts) && params.artifacts.length > 0;

      return hasContent || hasArtifacts;
    },
    { error: "Either content or artifacts are required" },
  );

export const permissionResponseParamsSchema = z.object({
  requestId: z.string().min(1, "requestId is required"),
  optionId: z.string().min(1, "optionId is required"),
  customInput: z.string().optional(),
  answers: z.record(z.string(), z.string()).optional(),
});

export const setConfigOptionParamsSchema = z.object({
  configId: z.string().min(1, "configId is required"),
  value: z.string().min(1, "value is required"),
});

export const refreshSessionParamsSchema = z.object({
  mcpServers: mcpServersSchema,
});

/**
 * Names of desktop-only local MCP servers designated for relaying into this
 * run (docs/cloud-mcp-relay.md). Names only — the sandbox never learns the
 * server's configuration.
 */
export const relayMcpServerNamesSchema = z
  .array(z.string().min(1).max(64))
  .max(20);

/** Desktop → sandbox reply to an `mcp_request` event. */
export const mcpResponseParamsSchema = z
  .object({
    requestId: z.string().min(1, "requestId is required"),
    server: z.string().min(1, "server is required"),
    payload: z.record(z.string(), z.unknown()).optional(),
    error: z.object({ code: z.number(), message: z.string() }).optional(),
  })
  .refine((params) => Boolean(params.payload) !== Boolean(params.error), {
    error: "Exactly one of payload or error is required",
  });

export const closeParamsSchema = z
  .object({
    localGitState: handoffLocalGitStateSchema.optional(),
  })
  .optional();

export const commandParamsSchemas = {
  user_message: userMessageParamsSchema,
  "posthog/user_message": userMessageParamsSchema,
  cancel: z.object({}).optional(),
  "posthog/cancel": z.object({}).optional(),
  close: closeParamsSchema,
  "posthog/close": closeParamsSchema,
  permission_response: permissionResponseParamsSchema,
  "posthog/permission_response": permissionResponseParamsSchema,
  set_config_option: setConfigOptionParamsSchema,
  "posthog/set_config_option": setConfigOptionParamsSchema,
  refresh_session: refreshSessionParamsSchema,
  "posthog/refresh_session": refreshSessionParamsSchema,
  "_posthog/refresh_session": refreshSessionParamsSchema,
  mcp_response: mcpResponseParamsSchema,
  "posthog/mcp_response": mcpResponseParamsSchema,
  "_posthog/mcp_response": mcpResponseParamsSchema,
} as const;

export type CommandMethod = keyof typeof commandParamsSchemas;

export function validateCommandParams(
  method: string,
  params: unknown,
): { success: true; data: unknown } | { success: false; error: string } {
  const schema =
    commandParamsSchemas[method as CommandMethod] ??
    commandParamsSchemas[
      method.replace(/^_?posthog\//, "") as keyof typeof commandParamsSchemas
    ];

  if (!schema) {
    return { success: false, error: `Unknown method: ${method}` };
  }

  const result = schema.safeParse(params);
  if (!result.success) {
    return { success: false, error: result.error.message };
  }

  return { success: true, data: result.data };
}
