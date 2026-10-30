import { z } from "zod";

export const startupFailureSchema = z.object({
  provider: z.enum(["claude", "codex", "pi"]),
  phase: z.enum(["session_setup", "sdk_initialization", "setup_hooks"]),
  reason: z
    .enum([
      "credential_unavailable",
      "credential_service_unavailable",
      "org_pin_api_key_conflict",
      "org_verify_failed",
      "org_pin_mismatch",
      "managed_settings_invalid",
      "remote_settings_required_unavailable",
      "gateway_signin_required",
      "gateway_access_denied",
      "proxy_invalid",
      "temp_dir_unusable",
      "cwd_unavailable",
      "shell_tool_missing",
      "session_held_by_background",
      "worktree_resume_refused",
      "worktree_unverified",
      "cli_version_too_old",
      "bypass_root",
      "sandbox_required_unavailable",
      "provider_not_allowed",
      "org_config_required_unavailable",
      "org_config_refused",
    ])
    .nullable(),
  retryability: z.enum(["requires_action", "transient", "unknown"]),
});

export type StartupFailure = z.infer<typeof startupFailureSchema>;

const startupErrorSchema = z.object({
  data: z.object({ startup_failure: startupFailureSchema }),
});

export function readStartupFailure(error: unknown): StartupFailure | undefined {
  const parsed = startupErrorSchema.safeParse(error);
  return parsed.success ? parsed.data.data.startup_failure : undefined;
}
