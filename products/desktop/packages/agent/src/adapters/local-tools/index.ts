import type { LocalTool, LocalToolCtx, LocalToolGateMeta } from "./registry";
import { cloneRepoTool } from "./tools/clone-repo";
import { finishTool } from "./tools/finish";
import { ghStackTool } from "./tools/gh-stack";
import { listAgentsTool } from "./tools/list-agents";
import { listReposTool } from "./tools/list-repos";
import { reportInsightTool } from "./tools/report-insight";
import { sendAgentMessageTool } from "./tools/send-agent-message";
import { showActionsTool } from "./tools/show-actions";
import { signedCommitTool } from "./tools/signed-commit";
import { signedMergeTool } from "./tools/signed-merge";
import { signedRewriteTool } from "./tools/signed-rewrite";
import { speakTool } from "./tools/speak";
import { uploadArtifactTool } from "./tools/upload-artifact";

export {
  LOCAL_TOOLS_MCP_NAME,
  type LocalTool,
  type LocalToolCtx,
  type LocalToolGateMeta,
  type LocalToolResult,
  qualifiedLocalToolName,
} from "./registry";

/** Every tool the general local MCP server can expose. Add new tools here. */
export const LOCAL_TOOLS: LocalTool[] = [
  signedCommitTool,
  signedMergeTool,
  signedRewriteTool,
  ghStackTool,
  listReposTool,
  cloneRepoTool,
  speakTool,
  showActionsTool,
  uploadArtifactTool,
  reportInsightTool,
  finishTool,
  listAgentsTool,
  sendAgentMessageTool,
];

/** Tools whose gate passes for the given context — the set to actually expose. */
export function enabledLocalTools(
  ctx: LocalToolCtx,
  meta: LocalToolGateMeta | undefined,
): LocalTool[] {
  return LOCAL_TOOLS.filter((t) => t.isEnabled(ctx, meta));
}
