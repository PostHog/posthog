/**
 * Handlers for the richer Codex app-server server-requests that carry a typed
 * response object rather than a yes/no decision string (requestUserInput,
 * permissions/requestApproval, mcpServer/elicitation). Each is surfaced through
 * ACP `requestPermission`; on cancel/error we default to the safe outcome so a
 * dropped prompt never silently grants access.
 */

import type {
  AgentSideConnection,
  PermissionOption,
  RequestPermissionResponse,
} from "@agentclientprotocol/sdk";
import { mcpToolKey, posthogToolMeta } from "@posthog/shared";
import type { Logger } from "../../utils/logger";
import { OPTION_PREFIX } from "../claude/questions/utils";
import { APP_SERVER_REQUESTS } from "./protocol";

// Native app-server shapes, re-declared locally so this module doesn't depend on
// the generated schema at build time.

interface ToolRequestUserInputOption {
  label: string;
  description: string;
}

interface ToolRequestUserInputQuestion {
  id: string;
  header: string;
  question: string;
  isOther: boolean;
  isSecret: boolean;
  options: ToolRequestUserInputOption[] | null;
}

interface ToolRequestUserInputParams {
  threadId: string;
  turnId: string;
  itemId: string;
  questions: ToolRequestUserInputQuestion[];
  autoResolutionMs: number | null;
}

interface ToolRequestUserInputResponse {
  answers: { [questionId: string]: { answers: string[] } };
}

interface AdditionalNetworkPermissions {
  enabled: boolean | null;
}

interface AdditionalFileSystemPermissions {
  read: string[] | null;
  write: string[] | null;
  globScanMaxDepth?: number;
  entries?: unknown[];
}

interface RequestPermissionProfile {
  network: AdditionalNetworkPermissions | null;
  fileSystem: AdditionalFileSystemPermissions | null;
}

interface PermissionsRequestApprovalParams {
  threadId: string;
  turnId: string;
  itemId: string;
  environmentId: string | null;
  startedAtMs: number;
  cwd: string;
  reason: string | null;
  permissions: RequestPermissionProfile;
}

interface GrantedPermissionProfile {
  network?: AdditionalNetworkPermissions;
  fileSystem?: AdditionalFileSystemPermissions;
}

type PermissionGrantScope = "turn" | "session";

interface PermissionsRequestApprovalResponse {
  permissions: GrantedPermissionProfile;
  scope: PermissionGrantScope;
}

type McpServerElicitationAction = "accept" | "decline" | "cancel";

interface McpServerElicitationRequestParams {
  threadId: string;
  turnId: string | null;
  serverName: string;
  mode: "form" | "url";
  message: string;
  // Only `message` is needed to render the prompt; the rest stays untyped.
  [key: string]: unknown;
}

interface McpServerElicitationRequestResponse {
  action: McpServerElicitationAction;
  content: unknown | null;
  _meta?: unknown | null;
}

export interface HandleServerRequestResult {
  // false → not a richer request; the caller handles it (simple approvals).
  handled: boolean;
  response: unknown;
}

export interface HandleServerRequestOptions {
  sessionId: string;
  logger?: Logger;
  /**
   * Resolve the in-flight MCP tool call for an elicitation's `serverName`. codex's
   * elicitation carries no tool/args, so supplying the originating `mcpToolCall`
   * lets the prompt render the real operation. Undefined → codex's generic text.
   */
  resolveMcpToolCall?: (
    serverName: string,
  ) => { server: string; tool: string; args: unknown } | undefined;
  /**
   * When an elicitation gates a known in-flight MCP call, accept it without
   * prompting if this returns true (e.g. a PostHog exec sub-tool the session's
   * permission policy does not gate). Elicitations with no resolvable call, or
   * from other servers, always prompt.
   */
  shouldAutoAcceptMcpToolCall?: (mcp: {
    server: string;
    tool: string;
    args: unknown;
  }) => boolean;
}

/**
 * Routes a server-initiated request to the matching richer-response handler.
 * Returns `{ handled: false }` for anything this module doesn't own.
 */
export async function handleServerRequest(
  method: string,
  params: unknown,
  client: Pick<AgentSideConnection, "requestPermission">,
  opts: HandleServerRequestOptions,
): Promise<HandleServerRequestResult> {
  try {
    switch (method) {
      case APP_SERVER_REQUESTS.TOOL_USER_INPUT:
        return {
          handled: true,
          response: await handleToolUserInput(
            params as ToolRequestUserInputParams,
            client,
            opts,
          ),
        };
      case APP_SERVER_REQUESTS.PERMISSIONS_APPROVAL:
        return {
          handled: true,
          response: await handlePermissionsApproval(
            params as PermissionsRequestApprovalParams,
            client,
            opts,
          ),
        };
      case APP_SERVER_REQUESTS.MCP_ELICITATION:
        return {
          handled: true,
          response: await handleMcpElicitation(
            params as McpServerElicitationRequestParams,
            client,
            opts,
          ),
        };
      default:
        return { handled: false, response: undefined };
    }
  } catch (err) {
    // Malformed payload fails closed to the safe default — never throw, never grant.
    opts.logger?.warn("server-request handler threw; failing closed", {
      method,
      error: String(err),
    });
    return { handled: true, response: safeDefaultFor(method) };
  }
}

function safeDefaultFor(method: string): unknown {
  if (method === APP_SERVER_REQUESTS.PERMISSIONS_APPROVAL) {
    return { permissions: {}, scope: "turn" };
  }
  if (method === APP_SERVER_REQUESTS.MCP_ELICITATION) {
    return { action: "decline", content: null, _meta: null };
  }
  return { answers: {} };
}

function buildQuestionOptions(
  question: ToolRequestUserInputQuestion,
): PermissionOption[] {
  return (question.options ?? []).map((opt, idx) => ({
    kind: "allow_once" as const,
    name: opt.label,
    optionId: `${OPTION_PREFIX}${idx}`,
    _meta: opt.description ? { description: opt.description } : undefined,
  }));
}

// Maps a selected optionId (`option_<idx>`) back to the chosen option's label.
function answerFromSelection(
  question: ToolRequestUserInputQuestion,
  optionId: string | undefined,
): string[] {
  if (!optionId || !optionId.startsWith(OPTION_PREFIX)) {
    return [];
  }
  const idx = Number(optionId.slice(OPTION_PREFIX.length));
  const opt = question.options?.[idx];
  return opt ? [opt.label] : [];
}

async function handleToolUserInput(
  params: ToolRequestUserInputParams,
  client: Pick<AgentSideConnection, "requestPermission">,
  opts: HandleServerRequestOptions,
): Promise<ToolRequestUserInputResponse> {
  const answers: ToolRequestUserInputResponse["answers"] = {};

  for (const question of params.questions ?? []) {
    // Default to "no answer" so cancel/failure leaves a well-formed empty response.
    answers[question.id] = { answers: [] };

    const options = buildQuestionOptions(question);
    // Free-text questions have no options; requestPermission can't collect them.
    if (options.length === 0) {
      continue;
    }

    let response: RequestPermissionResponse;
    try {
      response = await client.requestPermission({
        sessionId: opts.sessionId,
        options,
        toolCall: {
          toolCallId: `${params.itemId}:${question.id}`,
          title: question.question,
          kind: "other",
          // The host's QuestionPermission renders from `_meta.questions`; a bare
          // `header` renders empty. codex prompts one question per request.
          _meta: {
            codeToolKind: "question",
            questions: [
              {
                question: question.question,
                header: question.header,
                options: (question.options ?? []).map((opt) => ({
                  label: opt.label,
                  ...(opt.description?.trim()
                    ? { description: opt.description }
                    : {}),
                })),
              },
            ],
          },
        },
      });
    } catch (err) {
      opts.logger?.warn("requestUserInput prompt failed; leaving empty", {
        questionId: question.id,
        error: String(err),
      });
      continue;
    }

    if (response.outcome.outcome !== "selected") {
      continue;
    }
    answers[question.id] = {
      answers: answerFromSelection(question, response.outcome.optionId),
    };
  }

  return { answers };
}

async function handlePermissionsApproval(
  params: PermissionsRequestApprovalParams,
  client: Pick<AgentSideConnection, "requestPermission">,
  opts: HandleServerRequestOptions,
): Promise<PermissionsRequestApprovalResponse> {
  const denied: PermissionsRequestApprovalResponse = {
    permissions: {},
    scope: "turn",
  };

  let response: RequestPermissionResponse;
  try {
    response = await client.requestPermission({
      sessionId: opts.sessionId,
      options: [
        { kind: "allow_once", name: "Allow", optionId: "allow" },
        { kind: "reject_once", name: "Reject", optionId: "reject" },
      ],
      toolCall: {
        toolCallId: params.itemId,
        title: params.reason ?? "Grant additional permissions",
        kind: "other",
      },
    });
  } catch (err) {
    opts.logger?.warn("permissions approval prompt failed; denying", {
      itemId: params.itemId,
      error: String(err),
    });
    return denied;
  }

  if (
    response.outcome.outcome === "selected" &&
    response.outcome.optionId === "allow"
  ) {
    // Grant only what was requested, scoped to this turn (option is "allow_once").
    return {
      permissions: grantedFromRequested(params.permissions),
      scope: "turn",
    };
  }
  return denied;
}

function grantedFromRequested(
  requested: RequestPermissionProfile,
): GrantedPermissionProfile {
  const granted: GrantedPermissionProfile = {};
  if (requested.network) {
    granted.network = requested.network;
  }
  if (requested.fileSystem) {
    granted.fileSystem = requested.fileSystem;
  }
  return granted;
}

async function handleMcpElicitation(
  params: McpServerElicitationRequestParams,
  client: Pick<AgentSideConnection, "requestPermission">,
  opts: HandleServerRequestOptions,
): Promise<McpServerElicitationRequestResponse> {
  const declined: McpServerElicitationRequestResponse = {
    action: "decline",
    content: null,
    _meta: null,
  };

  // If the elicitation gates a known in-flight MCP call, carry its real tool +
  // args + `_meta.posthog` so the host renders the proper MCP permission.
  const mcp = opts.resolveMcpToolCall?.(params.serverName);
  if (mcp && opts.shouldAutoAcceptMcpToolCall?.(mcp)) {
    return { action: "accept", content: {}, _meta: null };
  }
  const toolCall = mcp
    ? {
        toolCallId: `${params.serverName}:elicitation`,
        title: params.message || `${params.serverName} requests input`,
        kind: "other" as const,
        rawInput: mcp.args,
        _meta: posthogToolMeta({
          toolName: mcpToolKey({ server: mcp.server, tool: mcp.tool }),
          mcp: { server: mcp.server, tool: mcp.tool },
        }),
      }
    : {
        toolCallId: `${params.serverName}:elicitation`,
        title: params.message || `${params.serverName} requests input`,
        kind: "other" as const,
      };

  let response: RequestPermissionResponse;
  try {
    response = await client.requestPermission({
      sessionId: opts.sessionId,
      options: [
        { kind: "allow_once", name: "Accept", optionId: "accept" },
        { kind: "reject_once", name: "Decline", optionId: "decline" },
      ],
      toolCall,
    });
  } catch (err) {
    opts.logger?.warn("elicitation prompt failed; declining", {
      serverName: params.serverName,
      error: String(err),
    });
    return declined;
  }

  if (response.outcome.outcome === "cancelled") {
    return { action: "cancel", content: null, _meta: null };
  }
  if (
    response.outcome.outcome === "selected" &&
    response.outcome.optionId === "accept"
  ) {
    // No structured form UI over requestPermission; accept with empty content.
    return { action: "accept", content: {}, _meta: null };
  }
  return declined;
}
