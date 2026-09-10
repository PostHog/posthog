import { z } from "zod/v4";

/**
 * The PostHog MCP exposes a single `exec` dispatcher tool that runs
 * subcommands like `call [--flags] <tool-name> [json]`. These helpers identify
 * that dispatcher, extract the delegated tool, and apply the externally
 * configured permission regex at sub-tool granularity.
 */

/**
 * Naming contract: the PostHog exec dispatcher is recognized only for server
 * names of the form `posthog` plus optional `_`-separated suffixes (e.g.
 * `posthog_cloud`). The dispatcher is always registered under the literal name
 * `posthog` (workspace-server auth-adapter), which is also reserved against
 * user MCP imports (core localMcpImport). Cloud provisioning must pass a
 * conforming name — a hyphenated or prefixed name (e.g. `posthog-eu`) is not
 * recognized and the exec guard silently won't apply.
 */
const POSTHOG_EXEC_TOOL_RE = /^mcp__posthog(?:_[^_]+)*__exec$/;

// Skip every `--flag` token after `call` (`--json`, `--confirm`, future ones)
// before capturing the sub-tool, and require the sub-tool to start with an
// alphanumeric. Matching only `--json` let `call --confirm dashboard-update`
// capture `--confirm` as the sub-tool, which never matches the destructive
// regex — so exactly the calls the dispatcher flags as destructive bypassed
// the permission gate.
const POSTHOG_CALL_COMMAND_RE =
  /^\s*call\s+(?:--\S+\s+)*([a-zA-Z0-9][a-zA-Z0-9_-]*)/;

const posthogExecInputSchema = z.looseObject({ command: z.string() });

export const DEFAULT_POSTHOG_EXEC_PERMISSION_REGEX_SOURCE =
  "(^|-)(partial-update|update|patch|delete|destroy)(-|$)";

export const posthogExecPermissionRegexSchema = z
  .string()
  .min(1, "PostHog exec permission regex cannot be empty")
  .refine(
    (source) => {
      try {
        compilePostHogExecPermissionRegex(source);
        return true;
      } catch {
        return false;
      }
    },
    { error: "PostHog exec permission regex must be valid" },
  );

export function compilePostHogExecPermissionRegex(source: string): RegExp {
  return new RegExp(source, "i");
}

/**
 * Resolves a session-metadata regex value to a compiled regex. Absent values
 * use the default; invalid values (non-string, empty, uncompilable) report via
 * `onInvalid` and fall back to the default rather than failing the session.
 */
export function resolvePostHogExecPermissionRegex(
  value: unknown,
  onInvalid?: (message: string) => void,
): RegExp {
  if (value === undefined || value === null) {
    return compilePostHogExecPermissionRegex(
      DEFAULT_POSTHOG_EXEC_PERMISSION_REGEX_SOURCE,
    );
  }
  const parsed = posthogExecPermissionRegexSchema.safeParse(value);
  if (!parsed.success) {
    onInvalid?.(
      parsed.error.issues[0]?.message ??
        "PostHog exec permission regex must be a valid regex string",
    );
    return compilePostHogExecPermissionRegex(
      DEFAULT_POSTHOG_EXEC_PERMISSION_REGEX_SOURCE,
    );
  }
  return compilePostHogExecPermissionRegex(parsed.data);
}

export function isPostHogExecTool(toolName: string): boolean {
  return POSTHOG_EXEC_TOOL_RE.test(toolName);
}

export function isPostHogExecDescriptor(descriptor: {
  server: string;
  tool: string;
}): boolean {
  return isPostHogExecTool(`mcp__${descriptor.server}__${descriptor.tool}`);
}

export function extractPostHogSubTool(toolInput: unknown): string | null {
  const parsed = posthogExecInputSchema.safeParse(toolInput);
  if (!parsed.success) return null;
  const match = parsed.data.command.match(POSTHOG_CALL_COMMAND_RE);
  return match ? (match[1] ?? null) : null;
}

export function matchesPostHogExecPermission(
  subTool: string,
  permissionRegex: RegExp,
): boolean {
  permissionRegex.lastIndex = 0;
  return permissionRegex.test(subTool);
}
