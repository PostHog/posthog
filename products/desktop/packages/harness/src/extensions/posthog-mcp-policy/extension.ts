import type {
  ExtensionAPI,
  ExtensionFactory,
  ToolCallEvent,
} from "@earendil-works/pi-coding-agent";
import type {
  McpToolPermissionDecision,
  McpToolPermissionRequest,
  McpToolPolicy,
} from "@posthog/shared";
import { buildToolName } from "../mcp/tool-bridge";

export interface PosthogMcpPolicyOptions {
  mcpToolPolicies?: McpToolPolicy[];
  requestMcpToolPermission?: (
    request: McpToolPermissionRequest,
  ) => Promise<McpToolPermissionDecision>;
}

function requestedArguments(event: ToolCallEvent): Record<string, unknown> {
  if (event.toolName !== "mcp" || typeof event.input.args !== "string") {
    return event.input;
  }

  try {
    const parsed: unknown = JSON.parse(event.input.args);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
  } catch {
    return {};
  }
  return {};
}

function requestedToolName(event: ToolCallEvent): string | undefined {
  if (event.toolName === "mcp") {
    return typeof event.input.tool === "string" ? event.input.tool : undefined;
  }

  return event.toolName;
}

export function createPosthogMcpPolicyExtension(
  options: PosthogMcpPolicyOptions = {},
): ExtensionFactory {
  return (pi: ExtensionAPI) => {
    const policies = new Map(
      (options.mcpToolPolicies ?? []).map((policy) => [
        buildToolName("mcp", policy.serverName, policy.toolName),
        { ...policy },
      ]),
    );

    pi.on("tool_call", async (event) => {
      const piToolName = requestedToolName(event);
      const policy = piToolName ? policies.get(piToolName) : undefined;
      if (!policy || policy.approvalState === "approved") {
        return;
      }

      if (policy.approvalState === "do_not_use") {
        return {
          block: true,
          reason: `The ${policy.serverName} tool ${policy.toolName} is disabled in PostHog MCP settings.`,
        };
      }

      if (!options.requestMcpToolPermission) {
        return {
          block: true,
          reason: `The ${policy.serverName} tool ${policy.toolName} requires approval in PostHog MCP settings.`,
        };
      }

      const decision = await options.requestMcpToolPermission({
        requestId: event.toolCallId,
        serverName: policy.serverName,
        toolName: policy.toolName,
        installationId: policy.installationId,
        arguments: requestedArguments(event),
        ...(policy.description ? { description: policy.description } : {}),
      });
      if (decision === "reject") {
        return {
          block: true,
          reason: `Permission rejected for ${policy.serverName}.${policy.toolName}.`,
        };
      }

      if (decision === "allow_always") {
        policy.approvalState = "approved";
      }
    });
  };
}

export default createPosthogMcpPolicyExtension();
