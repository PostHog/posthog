import type { HookCallback, HookInput } from "@anthropic-ai/claude-agent-sdk";
import { rewriteBashForRtk } from "@posthog/harness/extensions/rtk";
import type { Logger } from "../../../utils/logger";

export const createRtkRewriteHook =
  (rtkPrefix: string, logger: Logger): HookCallback =>
  async (input: HookInput, _toolUseID: string | undefined) => {
    if (input.hook_event_name !== "PreToolUse") return { continue: true };
    if (input.tool_name !== "Bash") return { continue: true };

    const toolInput = input.tool_input as { command?: string } | undefined;
    const command = toolInput?.command;
    if (typeof command !== "string") return { continue: true };

    const rewritten = rewriteBashForRtk(command, rtkPrefix);
    if (!rewritten) return { continue: true };

    logger.info(`[RtkRewriteHook] Rewriting: ${command} → ${rewritten}`);
    return {
      continue: true,
      hookSpecificOutput: {
        hookEventName: "PreToolUse" as const,
        updatedInput: { ...toolInput, command: rewritten },
      },
    };
  };
