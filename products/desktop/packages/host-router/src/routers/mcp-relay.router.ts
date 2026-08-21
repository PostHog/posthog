import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import {
  MCP_RELAY_SERVICE,
  type McpRelayService,
} from "@posthog/workspace-server/services/mcp-relay/identifiers";
import {
  closeRunInput,
  executeMcpRelayInput,
  executeMcpRelayOutput,
} from "@posthog/workspace-server/services/mcp-relay/schemas";

export const mcpRelayRouter = router({
  execute: publicProcedure
    .input(executeMcpRelayInput)
    .output(executeMcpRelayOutput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<McpRelayService>(MCP_RELAY_SERVICE)
        .execute(input.runId, input.server, input.payload),
    ),
  closeRun: publicProcedure
    .input(closeRunInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<McpRelayService>(MCP_RELAY_SERVICE)
        .closeRun(input.runId),
    ),
});
