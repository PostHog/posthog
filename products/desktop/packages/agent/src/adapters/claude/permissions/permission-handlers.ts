import type {
  AgentSideConnection,
  RequestPermissionRequest,
  RequestPermissionResponse,
} from "@agentclientprotocol/sdk";
import type {
  PermissionRuleValue,
  PermissionUpdate,
} from "@anthropic-ai/claude-agent-sdk";
import {
  extractPostHogSubTool,
  isPostHogExecTool,
  matchesPostHogExecPermission,
} from "../../../posthog-exec-permission";
import { text } from "../../../utils/acp-content";
import type { Logger } from "../../../utils/logger";
import { qualifiedLocalToolName } from "../../local-tools";
import { SPEAK_TOOL_NAME } from "../../local-tools/tools/speak";
import { toolInfoFromToolUse } from "../conversion/tool-use-to-acp";
import {
  getMcpToolApprovalState,
  getMcpToolMetadata,
} from "../mcp/tool-metadata";
import {
  getClaudePlansDir,
  getLatestAssistantText,
  isClaudePlanFilePath,
  isPlanReady,
} from "../plan/utils";
import {
  type AskUserQuestionInput,
  normalizeAskUserQuestionInput,
  OPTION_PREFIX,
  type QuestionItem,
} from "../questions/utils";
import { isToolAllowedForMode, WRITE_TOOLS } from "../tools";
import type { Session } from "../types";
import {
  buildExitPlanModePermissionOptions,
  buildPermissionOptions,
} from "./permission-options";

const SPEAK_TOOL_ID = qualifiedLocalToolName(SPEAK_TOOL_NAME);

export type ToolPermissionResult =
  | {
      behavior: "allow";
      updatedInput: Record<string, unknown>;
      updatedPermissions?: PermissionUpdate[];
    }
  | {
      behavior: "deny";
      message: string;
      interrupt?: boolean;
    };

interface ToolHandlerContext {
  session: Session;
  toolName: string;
  toolInput: Record<string, unknown>;
  toolUseID: string;
  suggestions?: PermissionUpdate[];
  signal?: AbortSignal;
  client: AgentSideConnection;
  sessionId: string;
  fileContentCache: { [key: string]: string };
  logger: Logger;
  updateConfigOption: (configId: string, value: string) => Promise<void>;
  applySessionMode: (modeId: string) => Promise<void>;
  allowedDomains?: string[];
  /** Shared with the streamed tool_use path; first emitter wins. */
  emittedToolCalls?: Set<string>;
  supportsTerminalOutput?: boolean;
}

// Task*/TodoWrite render as plans, never as standalone tool_calls.
function shouldEmitToolCall(toolName: string): boolean {
  return (
    toolName !== "TodoWrite" &&
    toolName !== "TaskCreate" &&
    toolName !== "TaskUpdate" &&
    toolName !== "TaskList" &&
    toolName !== "TaskGet"
  );
}

// The SDK can invoke canUseTool before the tool_use block streams; make
// sure the tool_call exists before the client is asked to approve it.
async function ensureToolCallEmitted(
  context: ToolHandlerContext,
): Promise<void> {
  const { emittedToolCalls, toolName, toolUseID, toolInput } = context;
  if (!emittedToolCalls || !shouldEmitToolCall(toolName)) {
    return;
  }
  if (emittedToolCalls.has(toolUseID)) {
    return;
  }
  emittedToolCalls.add(toolUseID);
  const toolInfo = toolInfoFromToolUse(
    { name: toolName, input: toolInput },
    {
      supportsTerminalOutput: context.supportsTerminalOutput,
      toolUseId: toolUseID,
      cachedFileContent: context.fileContentCache,
      cwd: context.session.cwd,
    },
  );
  await context.client.sessionUpdate({
    sessionId: context.sessionId,
    update: {
      _meta: {
        claudeCode: { toolName },
        ...(toolName === "Bash" && context.supportsTerminalOutput
          ? { terminal_info: { terminal_id: toolUseID } }
          : {}),
      },
      toolCallId: toolUseID,
      sessionUpdate: "tool_call",
      rawInput: toolInput,
      status: "pending",
      ...toolInfo,
    },
  });
}

// The cancellationSignal lets a turn cancel dismiss the client's open
// dialog ($/cancel_request) instead of leaving this await hanging.
async function requestPermissionFromClient(
  context: ToolHandlerContext,
  params: RequestPermissionRequest,
): Promise<RequestPermissionResponse> {
  await ensureToolCallEmitted(context);
  try {
    return await context.client.requestPermission(params);
  } catch (error) {
    if (context.signal?.aborted) {
      throw new Error("Tool use aborted", { cause: error });
    }
    throw error;
  }
}

async function emitToolDenial(
  context: ToolHandlerContext,
  message: string,
): Promise<void> {
  context.logger.info(`[canUseTool] Tool denied: ${context.toolName}`, {
    message,
  });
  await context.client.sessionUpdate({
    sessionId: context.sessionId,
    update: {
      sessionUpdate: "tool_call_update",
      toolCallId: context.toolUseID,
      status: "failed",
      content: [{ type: "content", content: text(message) }],
    },
  });
}

async function buildDenialResult(
  context: ToolHandlerContext,
  response: RequestPermissionResponse,
): Promise<ToolPermissionResult> {
  const feedback = (response._meta?.customInput as string | undefined)?.trim();
  const message = feedback
    ? `User refused permission to run tool with feedback: ${feedback}`
    : "User refused permission to run tool";
  await emitToolDenial(context, message);
  return { behavior: "deny", message, interrupt: !feedback };
}

function getPlanFromFile(
  session: Session,
  fileContentCache: { [key: string]: string },
): string | undefined {
  return (
    session.lastPlanContent ||
    (session.lastPlanFilePath
      ? fileContentCache[session.lastPlanFilePath]
      : undefined)
  );
}

function ensurePlanInInput(
  toolInput: Record<string, unknown>,
  fallbackPlan: string | undefined,
): Record<string, unknown> {
  const hasPlan = typeof (toolInput as { plan?: unknown })?.plan === "string";
  if (hasPlan || !fallbackPlan) {
    return toolInput;
  }
  return { ...toolInput, plan: fallbackPlan };
}

function extractPlanText(input: Record<string, unknown>): string | undefined {
  const plan = (input as { plan?: unknown })?.plan;
  return typeof plan === "string" ? plan : undefined;
}

async function createPlanValidationError(
  message: string,
  context: ToolHandlerContext,
): Promise<ToolPermissionResult> {
  await emitToolDenial(context, message);
  return { behavior: "deny", message, interrupt: false };
}

async function validatePlanContent(
  planText: string | undefined,
  context: ToolHandlerContext,
): Promise<{ valid: true } | { valid: false; error: ToolPermissionResult }> {
  if (!planText) {
    const message = `Plan not ready. Provide the full markdown plan in ExitPlanMode or write it to ${getClaudePlansDir()} before requesting approval.`;
    return {
      valid: false,
      error: await createPlanValidationError(message, context),
    };
  }

  if (!isPlanReady(planText)) {
    const message =
      "Plan not ready. Provide the full markdown plan in ExitPlanMode before requesting approval.";
    return {
      valid: false,
      error: await createPlanValidationError(message, context),
    };
  }

  return { valid: true };
}

async function requestPlanApproval(
  context: ToolHandlerContext,
  updatedInput: Record<string, unknown>,
): Promise<RequestPermissionResponse> {
  const { sessionId, toolUseID, session } = context;

  const toolInfo = toolInfoFromToolUse({
    name: context.toolName,
    input: updatedInput,
  });

  return await requestPermissionFromClient(context, {
    options: buildExitPlanModePermissionOptions(session.modeBeforePlan),
    sessionId,
    toolCall: {
      toolCallId: toolUseID,
      title: toolInfo.title,
      kind: toolInfo.kind,
      content: toolInfo.content,
      locations: toolInfo.locations,
      rawInput: { ...updatedInput, toolName: context.toolName },
    },
  });
}

async function applyPlanApproval(
  response: RequestPermissionResponse,
  context: ToolHandlerContext,
  updatedInput: Record<string, unknown>,
): Promise<ToolPermissionResult> {
  if (
    response.outcome?.outcome === "selected" &&
    (response.outcome.optionId === "auto" ||
      response.outcome.optionId === "default" ||
      response.outcome.optionId === "acceptEdits" ||
      response.outcome.optionId === "bypassPermissions")
  ) {
    await context.applySessionMode(response.outcome.optionId);
    await context.updateConfigOption("mode", response.outcome.optionId);

    return {
      behavior: "allow",
      updatedInput,
      updatedPermissions: context.suggestions ?? [
        {
          type: "setMode",
          mode: response.outcome.optionId,
          destination: "localSettings",
        },
      ],
    };
  }

  const customInput = (response._meta as Record<string, unknown> | undefined)
    ?.customInput as string | undefined;
  const feedback = customInput?.trim();

  const message = feedback
    ? `User rejected the plan with feedback: ${feedback}`
    : "User rejected the plan. Wait for the user to provide direction.";
  await emitToolDenial(context, message);
  return { behavior: "deny", message, interrupt: !feedback };
}

async function handleEnterPlanModeTool(
  context: ToolHandlerContext,
): Promise<ToolPermissionResult> {
  const { toolInput } = context;

  await context.applySessionMode("plan");
  await context.updateConfigOption("mode", "plan");

  return {
    behavior: "allow",
    updatedInput: toolInput as Record<string, unknown>,
  };
}

async function handleExitPlanModeTool(
  context: ToolHandlerContext,
): Promise<ToolPermissionResult> {
  const { session, toolInput, fileContentCache } = context;

  const planFromFile = getPlanFromFile(session, fileContentCache);
  const latestText = getLatestAssistantText(session.notificationHistory);
  const fallbackPlan = planFromFile || (latestText ?? undefined);
  const updatedInput = ensurePlanInInput(toolInput, fallbackPlan);
  const planText = extractPlanText(updatedInput);

  const validationResult = await validatePlanContent(planText, context);
  if (!validationResult.valid) {
    return validationResult.error;
  }

  const response = await requestPlanApproval(context, updatedInput);
  if (context.signal?.aborted || response.outcome?.outcome === "cancelled") {
    throw new Error("Tool use aborted");
  }
  return await applyPlanApproval(response, context, updatedInput);
}

function buildQuestionOptions(question: QuestionItem) {
  return (question.options || []).map((opt, idx) => ({
    kind: "allow_once" as const,
    name: opt.label,
    optionId: `${OPTION_PREFIX}${idx}`,
    _meta: opt.description ? { description: opt.description } : undefined,
  }));
}

async function handleAskUserQuestionTool(
  context: ToolHandlerContext,
): Promise<ToolPermissionResult> {
  const input = context.toolInput as AskUserQuestionInput;
  context.logger.info("[AskUserQuestion] Received input", { input });
  const questions = normalizeAskUserQuestionInput(input);
  context.logger.info("[AskUserQuestion] Normalized questions", { questions });

  if (!questions || questions.length === 0) {
    context.logger.warn("[AskUserQuestion] No questions found in input");
    return {
      behavior: "deny",
      message: "No questions provided",
    };
  }

  const { sessionId, toolUseID, toolInput } = context;
  const firstQuestion = questions[0];
  const options = buildQuestionOptions(firstQuestion);

  const toolInfo = toolInfoFromToolUse({
    name: context.toolName,
    input: toolInput,
  });

  const response = await requestPermissionFromClient(context, {
    options,
    sessionId,
    toolCall: {
      toolCallId: toolUseID,
      title: firstQuestion.question,
      kind: "other",
      content: toolInfo.content,
      _meta: {
        codeToolKind: "question",
        questions,
      },
    },
  });

  // A cancelled outcome carrying a message is a deliberate "park the
  // question" response (Slack relay, unattended cloud run) — deliver it to
  // the model as a denial so it knows to wait for the user instead of
  // deciding on its own. A bare cancel remains a tool-use abort.
  const customMessage = (response._meta as Record<string, unknown> | undefined)
    ?.message;
  if (
    !context.signal?.aborted &&
    response.outcome?.outcome === "cancelled" &&
    typeof customMessage === "string"
  ) {
    return {
      behavior: "deny",
      message: customMessage,
    };
  }

  if (context.signal?.aborted || response.outcome?.outcome === "cancelled") {
    throw new Error("Tool use aborted");
  }

  if (response.outcome?.outcome !== "selected") {
    return {
      behavior: "deny",
      message:
        typeof customMessage === "string"
          ? customMessage
          : "User cancelled the questions",
    };
  }

  const answers = response._meta?.answers as Record<string, string> | undefined;
  if (!answers || Object.keys(answers).length === 0) {
    return {
      behavior: "deny",
      message: "User did not provide answers",
    };
  }

  return {
    behavior: "allow",
    updatedInput: {
      ...(context.toolInput as Record<string, unknown>),
      answers,
    },
  };
}

async function handleDefaultPermissionFlow(
  context: ToolHandlerContext,
): Promise<ToolPermissionResult> {
  const { session, toolName, toolInput, toolUseID, sessionId, suggestions } =
    context;

  const toolInfo = toolInfoFromToolUse(
    { name: toolName, input: toolInput },
    { cachedFileContent: context.fileContentCache, cwd: session?.cwd },
  );

  const options = buildPermissionOptions(
    toolName,
    toolInput as Record<string, unknown>,
    session.settingsManager.getRepoRoot(),
    suggestions,
  );

  // Tag MCP tool calls so the renderer routes them through McpPermission,
  // which knows how to show `serverName - toolName (MCP)` plus the unwrapped
  // PostHog exec body. Without this, the dialog falls back to DefaultPermission
  // and just shows the bare tool name (e.g. "exec") with no context.
  const isMcpTool = toolName.startsWith("mcp__");

  const response = await requestPermissionFromClient(context, {
    options,
    sessionId,
    toolCall: {
      toolCallId: toolUseID,
      title: toolInfo.title,
      kind: toolInfo.kind,
      content: toolInfo.content,
      locations: toolInfo.locations,
      rawInput: { ...(toolInput as Record<string, unknown>), toolName },
      ...(isMcpTool ? { _meta: { claudeCode: { toolName } } } : {}),
    },
  });

  if (context.signal?.aborted || response.outcome?.outcome === "cancelled") {
    throw new Error("Tool use aborted");
  }

  if (
    response.outcome?.outcome === "selected" &&
    (response.outcome.optionId === "allow" ||
      response.outcome.optionId === "allow_always")
  ) {
    if (response.outcome.optionId === "allow_always") {
      const rules = extractAllowRules(suggestions, toolName);
      try {
        await session.settingsManager.addAllowRules(rules);
      } catch (error) {
        context.logger.warn(
          "[canUseTool] Failed to persist allow rules to repository settings",
          { error: error instanceof Error ? error.message : String(error) },
        );
      }
      return {
        behavior: "allow",
        updatedInput: toolInput as Record<string, unknown>,
        updatedPermissions: buildSessionPermissions(suggestions, rules),
      };
    }
    return {
      behavior: "allow",
      updatedInput: toolInput as Record<string, unknown>,
    };
  }

  return buildDenialResult(context, response);
}

function parseMcpToolName(toolName: string): {
  serverName: string;
  tool: string;
} {
  const parts = toolName.split("__");
  return {
    serverName: parts[1] ?? toolName,
    tool: parts.slice(2).join("__") || toolName,
  };
}

async function handleMcpApprovalFlow(
  context: ToolHandlerContext,
): Promise<ToolPermissionResult> {
  const { toolName, toolInput, toolUseID, sessionId } = context;

  const { serverName, tool: displayTool } = parseMcpToolName(toolName);
  const metadata = getMcpToolMetadata(toolName);
  const description = metadata?.description
    ? `\n\n${metadata.description}`
    : "";

  const response = await requestPermissionFromClient(context, {
    options: [
      { kind: "allow_once", name: "Yes", optionId: "allow" },
      {
        kind: "allow_always",
        name: "Yes, always allow",
        optionId: "allow_always",
      },
      {
        kind: "reject_once",
        name: "Type here to tell the agent what to do differently",
        optionId: "reject",
        _meta: { customInput: true },
      },
    ],
    sessionId,
    toolCall: {
      toolCallId: toolUseID,
      title: `The agent wants to call ${displayTool} (${serverName})`,
      kind: "other",
      content: description
        ? [{ type: "content" as const, content: text(description) }]
        : [],
      rawInput: { ...(toolInput as Record<string, unknown>), toolName },
    },
  });

  if (context.signal?.aborted || response.outcome?.outcome === "cancelled") {
    throw new Error("Tool use aborted");
  }

  if (
    response.outcome?.outcome === "selected" &&
    (response.outcome.optionId === "allow" ||
      response.outcome.optionId === "allow_always")
  ) {
    if (response.outcome.optionId === "allow_always") {
      return {
        behavior: "allow",
        updatedInput: toolInput as Record<string, unknown>,
        updatedPermissions: [
          {
            type: "addRules",
            rules: [{ toolName }],
            behavior: "allow",
            destination: "localSettings",
          },
        ],
      };
    }
    return {
      behavior: "allow",
      updatedInput: toolInput as Record<string, unknown>,
    };
  }

  return buildDenialResult(context, response);
}

async function handlePostHogExecApprovalFlow(
  context: ToolHandlerContext,
  subTool: string,
): Promise<ToolPermissionResult> {
  const { toolName, toolInput, toolUseID, sessionId, session } = context;

  const response = await requestPermissionFromClient(context, {
    options: [
      { kind: "allow_once", name: "Yes", optionId: "allow" },
      {
        kind: "allow_always",
        name: "Yes, always allow",
        optionId: "allow_always",
      },
      {
        kind: "reject_once",
        name: "Type here to tell the agent what to do differently",
        optionId: "reject",
        _meta: { customInput: true },
      },
    ],
    sessionId,
    toolCall: {
      toolCallId: toolUseID,
      title: `The agent wants to run \`${subTool}\` on PostHog`,
      kind: "other",
      content: [
        {
          type: "content" as const,
          content: text(
            "This will modify live PostHog data. Approve to run this sub-tool.",
          ),
        },
      ],
      rawInput: { ...(toolInput as Record<string, unknown>), toolName },
      _meta: { claudeCode: { toolName } },
    },
  });

  if (context.signal?.aborted || response.outcome?.outcome === "cancelled") {
    throw new Error("Tool use aborted");
  }

  if (
    response.outcome?.outcome === "selected" &&
    (response.outcome.optionId === "allow" ||
      response.outcome.optionId === "allow_always")
  ) {
    if (response.outcome.optionId === "allow_always") {
      try {
        await session.settingsManager.addPostHogExecApproval(subTool);
      } catch (error) {
        context.logger.warn(
          "[canUseTool] Failed to persist PostHog exec approval",
          { error: error instanceof Error ? error.message : String(error) },
        );
      }
    }
    return {
      behavior: "allow",
      updatedInput: toolInput as Record<string, unknown>,
    };
  }

  return buildDenialResult(context, response);
}

function handlePlanFileException(
  context: ToolHandlerContext,
): ToolPermissionResult | null {
  const { session, toolName, toolInput } = context;

  if (session.permissionMode !== "plan" || !WRITE_TOOLS.has(toolName)) {
    return null;
  }

  const filePath = (toolInput as { file_path?: string })?.file_path;
  if (!isClaudePlanFilePath(filePath)) {
    return null;
  }

  session.lastPlanFilePath = filePath;
  const content = (toolInput as { content?: string })?.content;
  if (typeof content === "string") {
    session.lastPlanContent = content;
  }

  return {
    behavior: "allow",
    updatedInput: toolInput as Record<string, unknown>,
  };
}

function extractAllowRules(
  suggestions: PermissionUpdate[] | undefined,
  toolName: string,
): PermissionRuleValue[] {
  if (!suggestions || suggestions.length === 0) {
    return [{ toolName }];
  }
  return suggestions
    .filter(
      (update) => update.type === "addRules" && update.behavior === "allow",
    )
    .flatMap((update) => ("rules" in update ? update.rules : []));
}

/**
 * Forwards any non-addRules suggestions from the SDK (e.g. addDirectories)
 * with their destination remapped to `session`. Our own allow rules are
 * persisted via `settingsManager.addAllowRules`, so the SDK must not write
 * them to its default per-cwd location.
 */
function buildSessionPermissions(
  suggestions: PermissionUpdate[] | undefined,
  rules: PermissionRuleValue[],
): PermissionUpdate[] {
  const passthrough = (suggestions ?? [])
    .filter(
      (update) => !(update.type === "addRules" && update.behavior === "allow"),
    )
    .map((update) => ({ ...update, destination: "session" as const }));
  if (rules.length === 0) {
    return passthrough;
  }
  return [
    { type: "addRules", rules, behavior: "allow", destination: "session" },
    ...passthrough,
  ];
}

function extractDomainFromUrl(url: string): string | null {
  try {
    return new URL(url).hostname;
  } catch {
    return null;
  }
}

function isDomainAllowed(hostname: string, allowedDomains: string[]): boolean {
  return allowedDomains.some((pattern) => {
    if (pattern.startsWith("*.")) {
      const suffix = pattern.slice(1); // ".example.com"
      return hostname === pattern.slice(2) || hostname.endsWith(suffix);
    }
    return hostname === pattern;
  });
}

export async function canUseTool(
  context: ToolHandlerContext,
): Promise<ToolPermissionResult> {
  const { toolName, toolInput, session, allowedDomains } = context;

  // Enforce domain allowlist for web tools
  if (allowedDomains && allowedDomains.length > 0) {
    if (toolName === "WebFetch" || toolName === "WebSearch") {
      const url = toolInput.url as string | undefined;
      if (url) {
        const hostname = extractDomainFromUrl(url);
        if (hostname && !isDomainAllowed(hostname, allowedDomains)) {
          const message = `Domain "${hostname}" is not in the allowed list: ${allowedDomains.join(", ")}`;
          await emitToolDenial(context, message);
          return { behavior: "deny", message, interrupt: false };
        }
      }
    }
  }

  if (toolName.startsWith("mcp__")) {
    const approvalState = getMcpToolApprovalState(toolName);

    if (approvalState === "do_not_use") {
      const message =
        "This tool has been blocked. To re-enable it, go to Settings > MCP Servers in PostHog.";
      await emitToolDenial(context, message);
      return { behavior: "deny", message, interrupt: false };
    }

    // Narration is a fire-and-forget no-op on the agent side; a permission
    // prompt for it interrupts the user to approve a line they may never hear.
    // An explicit do_not_use block above still wins.
    if (toolName === SPEAK_TOOL_ID) {
      return {
        behavior: "allow",
        updatedInput: toolInput as Record<string, unknown>,
      };
    }

    // An explicit needs_approval setting always prompts — it must precede the
    // PostHog exec gate so a remembered sub-tool approval or a local hands-off
    // mode cannot silently allow a tool the user asked to be asked about.
    if (approvalState === "needs_approval") {
      return handleMcpApprovalFlow(context);
    }

    if (session.posthogExecPermissionRegex && isPostHogExecTool(toolName)) {
      const subTool = extractPostHogSubTool(toolInput);
      if (
        subTool &&
        matchesPostHogExecPermission(
          subTool,
          session.posthogExecPermissionRegex,
        )
      ) {
        if (session.settingsManager.hasPostHogExecApproval(subTool)) {
          return {
            behavior: "allow",
            updatedInput: toolInput as Record<string, unknown>,
          };
        }
        // Local hands-off modes retain their normal no-prompt behavior. Cloud
        // sessions must send the request to AgentServer, which uses the run's
        // effective mode to relay interactive approvals and auto-approve
        // background runs.
        if (
          !session.cloudMode &&
          (session.permissionMode === "auto" ||
            session.permissionMode === "bypassPermissions")
        ) {
          return {
            behavior: "allow",
            updatedInput: toolInput as Record<string, unknown>,
          };
        }
        return handlePostHogExecApprovalFlow(context, subTool);
      }
    }
  }

  if (isToolAllowedForMode(toolName, session.permissionMode)) {
    return {
      behavior: "allow",
      updatedInput: toolInput as Record<string, unknown>,
    };
  }

  if (toolName === "EnterPlanMode") {
    return handleEnterPlanModeTool(context);
  }

  if (toolName === "ExitPlanMode") {
    return handleExitPlanModeTool(context);
  }

  if (toolName === "AskUserQuestion") {
    return handleAskUserQuestionTool(context);
  }

  const planFileResult = handlePlanFileException(context);
  if (planFileResult) {
    return planFileResult;
  }

  // In plan mode, deny tools that aren't in the allowed set. The agent must
  // write its plan to ~/.claude/plans/ and call ExitPlanMode before it can
  // use write or bash tools. Without this guard, cloud runs auto-approve
  // restricted tools and the agent skips planning entirely.
  if (session.permissionMode === "plan") {
    const message =
      "This tool is not available in plan mode. Write your plan " +
      `to a file in ${getClaudePlansDir()} and call ExitPlanMode when ready.`;
    await emitToolDenial(context, message);
    return { behavior: "deny", message, interrupt: false };
  }

  return handleDefaultPermissionFlow(context);
}
