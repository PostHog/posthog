import { MCP_APPS_SERVICE } from "@posthog/core/mcp-apps/identifiers";
import type { McpAppsService } from "@posthog/core/mcp-apps/mcp-apps";
import {
  getToolDefinitionInput,
  getUiResourceByUriInput,
  getUiResourceInput,
  hasUiForToolInput,
  McpAppsServiceEvent,
  mcpAppsSubscriptionInput,
  mcpUiResourceSchema,
  openLinkInput,
  proxyResourceReadInput,
  proxyToolCallInput,
} from "@posthog/core/mcp-apps/schemas";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";

export const mcpAppsRouter = router({
  getUiResource: publicProcedure
    .input(getUiResourceInput)
    .output(mcpUiResourceSchema.nullable())
    .query(({ ctx, input }) =>
      ctx.container
        .get<McpAppsService>(MCP_APPS_SERVICE)
        .getUiResourceForTool(input.toolKey),
    ),

  hasUiForTool: publicProcedure
    .input(hasUiForToolInput)
    .query(({ ctx, input }) =>
      ctx.container
        .get<McpAppsService>(MCP_APPS_SERVICE)
        .hasUiForTool(input.toolKey),
    ),

  getUiResourceByUri: publicProcedure
    .input(getUiResourceByUriInput)
    .output(mcpUiResourceSchema.nullable())
    .query(({ ctx, input }) =>
      ctx.container
        .get<McpAppsService>(MCP_APPS_SERVICE)
        .getUiResourceByUri(input.serverName, input.resourceUri),
    ),

  getToolDefinition: publicProcedure
    .input(getToolDefinitionInput)
    .query(({ ctx, input }) =>
      ctx.container
        .get<McpAppsService>(MCP_APPS_SERVICE)
        .getToolDefinition(input.toolKey),
    ),

  proxyToolCall: publicProcedure
    .input(proxyToolCallInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<McpAppsService>(MCP_APPS_SERVICE)
        .proxyToolCall(input.serverName, input.toolName, input.args),
    ),

  proxyResourceRead: publicProcedure
    .input(proxyResourceReadInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<McpAppsService>(MCP_APPS_SERVICE)
        .proxyResourceRead(input.serverName, input.uri),
    ),

  openLink: publicProcedure
    .input(openLinkInput)
    .mutation(({ ctx, input }) =>
      ctx.container.get<McpAppsService>(MCP_APPS_SERVICE).openLink(input.url),
    ),

  onToolInput: publicProcedure
    .input(mcpAppsSubscriptionInput)
    .subscription(async function* (opts) {
      const service = opts.ctx.container.get<McpAppsService>(MCP_APPS_SERVICE);
      const targetToolKey = opts.input.toolKey;
      for await (const event of service.toIterable(
        McpAppsServiceEvent.ToolInput,
        { signal: opts.signal },
      )) {
        if (event.toolKey === targetToolKey) {
          yield event;
        }
      }
    }),

  onToolResult: publicProcedure
    .input(mcpAppsSubscriptionInput)
    .subscription(async function* (opts) {
      const service = opts.ctx.container.get<McpAppsService>(MCP_APPS_SERVICE);
      const targetToolKey = opts.input.toolKey;
      for await (const event of service.toIterable(
        McpAppsServiceEvent.ToolResult,
        { signal: opts.signal },
      )) {
        if (event.toolKey === targetToolKey) {
          yield event;
        }
      }
    }),

  onToolCancelled: publicProcedure
    .input(mcpAppsSubscriptionInput)
    .subscription(async function* (opts) {
      const service = opts.ctx.container.get<McpAppsService>(MCP_APPS_SERVICE);
      const targetToolKey = opts.input.toolKey;
      for await (const event of service.toIterable(
        McpAppsServiceEvent.ToolCancelled,
        { signal: opts.signal },
      )) {
        if (event.toolKey === targetToolKey) {
          yield event;
        }
      }
    }),

  onDiscoveryComplete: publicProcedure.subscription(async function* (opts) {
    const service = opts.ctx.container.get<McpAppsService>(MCP_APPS_SERVICE);
    for await (const event of service.toIterable(
      McpAppsServiceEvent.DiscoveryComplete,
      { signal: opts.signal },
    )) {
      yield event;
    }
  }),
});
