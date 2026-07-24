import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { PermissionRuleValue } from "@anthropic-ai/claude-agent-sdk";
import { minimatch } from "minimatch";
import { AsyncMutex } from "../../../utils/async-mutex";
import { resolveMainRepoPath } from "./repo-path";

const ACP_TOOL_NAME_PREFIX = "mcp__acp__";

const acpToolNames = {
  read: `${ACP_TOOL_NAME_PREFIX}Read`,
  edit: `${ACP_TOOL_NAME_PREFIX}Edit`,
  write: `${ACP_TOOL_NAME_PREFIX}Write`,
  bash: `${ACP_TOOL_NAME_PREFIX}Bash`,
};

const SHELL_OPERATORS = ["&&", "||", ";", "|", "$(", "`", "\n"];

function containsShellOperator(str: string): boolean {
  return SHELL_OPERATORS.some((op) => str.includes(op));
}

const FILE_EDITING_TOOLS = [acpToolNames.edit, acpToolNames.write];

const FILE_READING_TOOLS = [acpToolNames.read];

const TOOL_ARG_ACCESSORS: Record<
  string,
  (input: Record<string, unknown>) => string | undefined
> = {
  [acpToolNames.read]: (input) => input?.file_path as string | undefined,
  [acpToolNames.edit]: (input) => input?.file_path as string | undefined,
  [acpToolNames.write]: (input) => input?.file_path as string | undefined,
  [acpToolNames.bash]: (input) => input?.command as string | undefined,
};

interface ParsedRule {
  toolName: string;
  argument?: string;
  isWildcard?: boolean;
}

function parseRule(rule: string): ParsedRule {
  const match = rule.match(/^(\w+)(?:\((.+)\))?$/);
  if (!match) {
    return { toolName: rule };
  }
  const toolName = match[1] ?? rule;
  const argument = match[2];
  if (argument?.endsWith(":*")) {
    return {
      toolName,
      argument: argument.slice(0, -2),
      isWildcard: true,
    };
  }
  return { toolName, argument };
}

function normalizePath(filePath: string, cwd: string): string {
  let resolved = filePath;
  if (resolved.startsWith("~/")) {
    resolved = path.join(os.homedir(), resolved.slice(2));
  } else if (resolved.startsWith("./")) {
    resolved = path.join(cwd, resolved.slice(2));
  } else if (!path.isAbsolute(resolved)) {
    resolved = path.join(cwd, resolved);
  }
  return path.normalize(resolved).replace(/\\/g, "/");
}

function matchesGlob(pattern: string, filePath: string, cwd: string): boolean {
  const normalizedPattern = normalizePath(pattern, cwd);
  const normalizedPath = normalizePath(filePath, cwd);
  return minimatch(normalizedPath, normalizedPattern, {
    dot: true,
    matchBase: false,
    nocase: process.platform === "win32",
  });
}

function matchesRule(
  rule: ParsedRule,
  toolName: string,
  toolInput: unknown,
  cwd: string,
): boolean {
  const ruleAppliesToTool =
    (rule.toolName === "Bash" && toolName === acpToolNames.bash) ||
    (rule.toolName === "Edit" && FILE_EDITING_TOOLS.includes(toolName)) ||
    (rule.toolName === "Read" && FILE_READING_TOOLS.includes(toolName)) ||
    (rule.toolName === toolName && !rule.argument);

  if (!ruleAppliesToTool) {
    return false;
  }

  if (!rule.argument) {
    return true;
  }

  const argAccessor = TOOL_ARG_ACCESSORS[toolName];
  if (!argAccessor) {
    return true;
  }

  const actualArg = argAccessor(toolInput as Record<string, unknown>);
  if (!actualArg) {
    return false;
  }

  if (toolName === acpToolNames.bash) {
    if (rule.isWildcard) {
      if (!actualArg.startsWith(rule.argument)) {
        return false;
      }
      const remainder = actualArg.slice(rule.argument.length);
      if (containsShellOperator(remainder)) {
        return false;
      }
      return true;
    }
    return actualArg === rule.argument;
  }

  return matchesGlob(rule.argument, actualArg, cwd);
}

function formatRule(rule: PermissionRuleValue): string {
  return rule.ruleContent
    ? `${rule.toolName}(${rule.ruleContent})`
    : rule.toolName;
}

async function writeFileAtomic(filePath: string, data: string): Promise<void> {
  const tmpPath = `${filePath}.${process.pid}.${Date.now()}.tmp`;
  await fs.promises.writeFile(tmpPath, data);
  try {
    await fs.promises.rename(tmpPath, filePath);
  } catch (error) {
    await fs.promises.rm(tmpPath, { force: true });
    throw error;
  }
}

async function loadSettingsFile(
  filePath: string | undefined,
): Promise<ClaudeCodeSettings> {
  if (!filePath) {
    return {};
  }
  try {
    const content = await fs.promises.readFile(filePath, "utf-8");
    return JSON.parse(content) as ClaudeCodeSettings;
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ENOENT") {
      return {};
    }
    process.stderr.write(
      `[SettingsManager] Failed to load settings from ${filePath}: ${error}\n`,
    );
    return {};
  }
}

/**
 * Reads a settings file for a read-modify-write cycle. Unlike
 * `loadSettingsFile`, this throws on any error other than ENOENT — we refuse
 * to overwrite a file we couldn't parse, because doing so would wipe the
 * user's existing settings (other allow/deny/ask rules, env, model, etc).
 */
async function readSettingsFileForUpdate(
  filePath: string,
): Promise<ClaudeCodeSettings> {
  try {
    const content = await fs.promises.readFile(filePath, "utf-8");
    return JSON.parse(content) as ClaudeCodeSettings;
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ENOENT") {
      return {};
    }
    throw error;
  }
}

export interface PermissionSettings {
  allow?: string[];
  deny?: string[];
  ask?: string[];
  additionalDirectories?: string[];
  defaultMode?: string;
}

export interface ClaudeCodeSettings {
  permissions?: PermissionSettings;
  env?: Record<string, string>;
  model?: string;
  availableModels?: string[];
  posthogApprovedExecTools?: string[];
}

type SettingsLayer = "user" | "project" | "local" | "enterprise";

export type PermissionDecision = "allow" | "deny" | "ask";

export interface PermissionCheckResult {
  decision: PermissionDecision;
  rule?: string;
  source?: "allow" | "deny" | "ask";
}

export function getManagedSettingsPath(): string {
  switch (process.platform) {
    case "darwin":
      return "/Library/Application Support/ClaudeCode/managed-settings.json";
    case "linux":
      return "/etc/claude-code/managed-settings.json";
    case "win32":
      return "C:\\Program Files\\ClaudeCode\\managed-settings.json";
    default:
      return "/etc/claude-code/managed-settings.json";
  }
}

export function mergeAvailableModels(
  existing: string[] | undefined,
  incoming: string[] | undefined,
  layer: SettingsLayer,
): string[] | undefined {
  if (incoming === undefined) {
    return existing;
  }

  if (layer === "enterprise") {
    return Array.from(new Set(incoming));
  }

  return Array.from(new Set([...(existing ?? []), ...incoming]));
}

export class SettingsManager {
  private cwd: string;
  private repoRoot: string;
  private userSettings: ClaudeCodeSettings = {};
  private projectSettings: ClaudeCodeSettings = {};
  private localSettings: ClaudeCodeSettings = {};
  private enterpriseSettings: ClaudeCodeSettings = {};
  private mergedSettings: ClaudeCodeSettings = {};
  private initialized = false;
  private initPromise: Promise<void> | null = null;
  private writeMutex = new AsyncMutex();

  constructor(cwd: string) {
    this.cwd = cwd;
    this.repoRoot = cwd;
  }

  async initialize(): Promise<void> {
    if (this.initialized) return;
    if (this.initPromise) return this.initPromise;
    this.initPromise = this.loadAllSettings().then(() => {
      this.initialized = true;
      this.initPromise = null;
    });
    return this.initPromise;
  }

  private getUserSettingsPath(): string {
    const configDir =
      process.env.CLAUDE_CONFIG_DIR || path.join(os.homedir(), ".claude");
    return path.join(configDir, "settings.json");
  }

  private getProjectSettingsPath(): string {
    return path.join(this.cwd, ".claude", "settings.json");
  }

  /**
   * Local settings are anchored to the primary worktree so every worktree of
   * the same repository shares a single `.claude/settings.local.json`. This
   * avoids re-prompting for the same permission in every worktree.
   */
  private getLocalSettingsPath(): string {
    return path.join(this.repoRoot, ".claude", "settings.local.json");
  }

  private async loadAllSettings(): Promise<void> {
    this.repoRoot = await resolveMainRepoPath(this.cwd);
    const [userSettings, projectSettings, localSettings, enterpriseSettings] =
      await Promise.all([
        loadSettingsFile(this.getUserSettingsPath()),
        loadSettingsFile(this.getProjectSettingsPath()),
        loadSettingsFile(this.getLocalSettingsPath()),
        loadSettingsFile(getManagedSettingsPath()),
      ]);
    this.userSettings = userSettings;
    this.projectSettings = projectSettings;
    this.localSettings = localSettings;
    this.enterpriseSettings = enterpriseSettings;
    this.mergeAllSettings();
  }

  private mergeAllSettings(): void {
    const allSettings: Array<{
      layer: SettingsLayer;
      settings: ClaudeCodeSettings;
    }> = [
      { layer: "user", settings: this.userSettings },
      { layer: "project", settings: this.projectSettings },
      { layer: "local", settings: this.localSettings },
      { layer: "enterprise", settings: this.enterpriseSettings },
    ];

    const permissions: PermissionSettings = {
      allow: [],
      deny: [],
      ask: [],
    };
    const merged: ClaudeCodeSettings = { permissions };
    const posthogApprovedExecTools = new Set<string>();

    for (const { layer, settings } of allSettings) {
      if (settings.permissions) {
        if (settings.permissions.allow) {
          permissions.allow?.push(...settings.permissions.allow);
        }
        if (settings.permissions.deny) {
          permissions.deny?.push(...settings.permissions.deny);
        }
        if (settings.permissions.ask) {
          permissions.ask?.push(...settings.permissions.ask);
        }
        if (settings.permissions.additionalDirectories) {
          permissions.additionalDirectories = [
            ...(permissions.additionalDirectories || []),
            ...settings.permissions.additionalDirectories,
          ];
        }
        if (settings.permissions.defaultMode) {
          permissions.defaultMode = settings.permissions.defaultMode;
        }
      }
      if (settings.env) {
        merged.env = { ...merged.env, ...settings.env };
      }
      if (settings.model) {
        merged.model = settings.model;
      }
      merged.availableModels = mergeAvailableModels(
        merged.availableModels,
        settings.availableModels,
        layer,
      );
      if (settings.posthogApprovedExecTools) {
        for (const tool of settings.posthogApprovedExecTools) {
          posthogApprovedExecTools.add(tool);
        }
      }
    }

    if (posthogApprovedExecTools.size > 0) {
      merged.posthogApprovedExecTools = Array.from(posthogApprovedExecTools);
    }

    this.mergedSettings = merged;
  }

  checkPermission(toolName: string, toolInput: unknown): PermissionCheckResult {
    const permissions = this.mergedSettings.permissions;
    if (!permissions) {
      return { decision: "ask" };
    }

    for (const rule of permissions.deny || []) {
      const parsed = parseRule(rule);
      if (matchesRule(parsed, toolName, toolInput, this.cwd)) {
        return { decision: "deny", rule, source: "deny" };
      }
    }

    for (const rule of permissions.allow || []) {
      const parsed = parseRule(rule);
      if (matchesRule(parsed, toolName, toolInput, this.cwd)) {
        return { decision: "allow", rule, source: "allow" };
      }
    }

    for (const rule of permissions.ask || []) {
      const parsed = parseRule(rule);
      if (matchesRule(parsed, toolName, toolInput, this.cwd)) {
        return { decision: "ask", rule, source: "ask" };
      }
    }

    return { decision: "ask" };
  }

  getSettings(): ClaudeCodeSettings {
    return this.mergedSettings;
  }

  getCwd(): string {
    return this.cwd;
  }

  getRepoRoot(): string {
    return this.repoRoot;
  }

  /**
   * Persists allow rules to `<primary-worktree>/.claude/settings.local.json`.
   * Because local settings are resolved against the primary worktree, every
   * worktree of the same repository picks up the new rule on next load.
   *
   * Writes are serialised via `writeMutex` to prevent concurrent callers from
   * clobbering each other, and use a temp-file + rename to keep the file
   * consistent if the process dies mid-write.
   */
  async addAllowRules(rules: PermissionRuleValue[]): Promise<void> {
    if (rules.length === 0) return;
    if (!this.initialized) await this.initialize();
    await this.writeMutex.acquire();
    try {
      const filePath = this.getLocalSettingsPath();
      const existing = await readSettingsFileForUpdate(filePath);
      const permissions: PermissionSettings = {
        ...(existing.permissions ?? {}),
      };
      const current = new Set(permissions.allow ?? []);
      for (const rule of rules) {
        current.add(formatRule(rule));
      }
      permissions.allow = Array.from(current);
      const next: ClaudeCodeSettings = { ...existing, permissions };
      await fs.promises.mkdir(path.dirname(filePath), { recursive: true });
      await writeFileAtomic(filePath, `${JSON.stringify(next, null, 2)}\n`);

      this.localSettings = next;
      this.mergeAllSettings();
    } finally {
      this.writeMutex.release();
    }
  }

  hasPostHogExecApproval(subTool: string): boolean {
    return (
      this.mergedSettings.posthogApprovedExecTools?.includes(subTool) ?? false
    );
  }

  /**
   * Persists an approved PostHog MCP `exec` sub-tool (e.g. `experiment-update`)
   * to the local settings file so future calls skip the prompt. Mirrors
   * `addAllowRules` — serialised via `writeMutex`, atomic temp-file + rename.
   */
  async addPostHogExecApproval(subTool: string): Promise<void> {
    if (!subTool) return;
    if (!this.initialized) await this.initialize();
    await this.writeMutex.acquire();
    try {
      const filePath = this.getLocalSettingsPath();
      const existing = await readSettingsFileForUpdate(filePath);
      const current = new Set(existing.posthogApprovedExecTools ?? []);
      if (current.has(subTool)) {
        return;
      }
      current.add(subTool);
      const next: ClaudeCodeSettings = {
        ...existing,
        posthogApprovedExecTools: Array.from(current),
      };
      await fs.promises.mkdir(path.dirname(filePath), { recursive: true });
      await writeFileAtomic(filePath, `${JSON.stringify(next, null, 2)}\n`);

      this.localSettings = next;
      this.mergeAllSettings();
    } finally {
      this.writeMutex.release();
    }
  }

  async setCwd(cwd: string): Promise<void> {
    if (this.cwd === cwd) return;
    if (this.initPromise) await this.initPromise;
    this.dispose();
    this.cwd = cwd;
    this.initialized = false;
    await this.initialize();
  }

  dispose(): void {
    this.initialized = false;
  }
}
