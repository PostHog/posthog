import type { PermissionUpdate } from "@anthropic-ai/claude-agent-sdk";
import { ALLOW_BYPASS } from "../../../utils/common";
import { BASH_TOOLS, READ_TOOLS, SEARCH_TOOLS, WRITE_TOOLS } from "../tools";

export interface PermissionOption {
  kind: "allow_once" | "allow_always" | "reject_once" | "reject_always";
  name: string;
  optionId: string;
  _meta?: { description?: string; customInput?: boolean };
}

function permissionOptions(allowAlwaysLabel: string): PermissionOption[] {
  return [
    { kind: "allow_once", name: "Yes", optionId: "allow" },
    { kind: "allow_always", name: allowAlwaysLabel, optionId: "allow_always" },
    {
      kind: "reject_once",
      name: "No, and tell the agent what to do differently",
      optionId: "reject",
      _meta: { customInput: true },
    },
  ];
}

export function buildPermissionOptions(
  toolName: string,
  toolInput: Record<string, unknown>,
  repoRoot?: string,
  suggestions?: PermissionUpdate[],
): PermissionOption[] {
  if (BASH_TOOLS.has(toolName)) {
    const rawRuleContent = suggestions
      ?.flatMap((s) => ("rules" in s ? s.rules : []))
      .find((r) => r.toolName === "Bash" && r.ruleContent)?.ruleContent;
    const ruleContent = rawRuleContent?.replace(/:?\*$/, "");

    const command = toolInput?.command as string | undefined;
    const cmdName = command?.split(/\s+/)[0] ?? "this command";
    const scopeLabel = repoRoot ? ` in ${repoRoot}` : "";
    const label = ruleContent ?? `\`${cmdName}\` commands`;

    return permissionOptions(
      `Yes, and don't ask again for ${label}${scopeLabel}`,
    );
  }

  if (toolName === "BashOutput") {
    return permissionOptions("Yes, allow all background process reads");
  }

  if (toolName === "KillShell") {
    return permissionOptions("Yes, allow killing processes");
  }

  if (WRITE_TOOLS.has(toolName)) {
    return permissionOptions("Yes, allow all edits during this session");
  }

  if (READ_TOOLS.has(toolName)) {
    return permissionOptions("Yes, allow all reads during this session");
  }

  if (SEARCH_TOOLS.has(toolName)) {
    return permissionOptions("Yes, allow all searches during this session");
  }

  if (toolName === "WebFetch") {
    const url = toolInput?.url as string | undefined;
    let domain = "";
    try {
      domain = url ? new URL(url).hostname : "";
    } catch {}
    return permissionOptions(
      domain
        ? `Yes, allow all fetches from ${domain}`
        : "Yes, allow all fetches",
    );
  }

  if (toolName === "WebSearch") {
    return permissionOptions("Yes, allow all web searches");
  }

  if (toolName === "Task") {
    return permissionOptions("Yes, allow all sub-tasks");
  }

  if (
    toolName === "TaskCreate" ||
    toolName === "TaskUpdate" ||
    toolName === "TaskGet" ||
    toolName === "TaskList"
  ) {
    return permissionOptions("Yes, allow all task updates");
  }

  return permissionOptions("Yes, always allow");
}

const CONTINUE_LABELS: Record<string, string> = {
  auto: 'Yes, continue in "auto" mode',
  acceptEdits: "Yes, continue auto-accepting edits",
  default: "Yes, continue manually approving edits",
  bypassPermissions: "Yes, continue bypassing all permissions",
};

export function buildExitPlanModePermissionOptions(
  previousMode?: string,
): PermissionOption[] {
  const options: PermissionOption[] = [];

  if (ALLOW_BYPASS) {
    options.push({
      kind: "allow_always",
      name: "Yes, bypass all permissions",
      optionId: "bypassPermissions",
    });
  }

  options.push(
    {
      kind: "allow_always",
      name: 'Yes, and use "auto" mode',
      optionId: "auto",
    },
    {
      kind: "allow_always",
      name: "Yes, and auto-accept edits",
      optionId: "acceptEdits",
    },
    {
      kind: "allow_once",
      name: "Yes, and manually approve edits",
      optionId: "default",
    },
  );

  const previousIndex = previousMode
    ? options.findIndex((opt) => opt.optionId === previousMode)
    : -1;
  if (previousIndex > 0) {
    const [previous] = options.splice(previousIndex, 1);
    const continueLabel = CONTINUE_LABELS[previous.optionId];
    options.unshift(
      continueLabel ? { ...previous, name: continueLabel } : previous,
    );
  } else if (previousIndex === 0) {
    const continueLabel = CONTINUE_LABELS[options[0].optionId];
    if (continueLabel) {
      options[0] = { ...options[0], name: continueLabel };
    }
  }

  options.push({
    kind: "reject_once",
    name: "No, and tell the agent what to do differently",
    optionId: "reject_with_feedback",
    _meta: { customInput: true },
  });

  return options;
}
