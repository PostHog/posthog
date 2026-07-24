import type { LocalTool, LocalToolCtx, LocalToolGateMeta } from "./registry";
import { cloneRepoTool } from "./tools/clone-repo";
import { finishTool } from "./tools/finish";
import { listReposTool } from "./tools/list-repos";
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
  listReposTool,
  cloneRepoTool,
  speakTool,
  uploadArtifactTool,
  finishTool,
];

/** Tools whose gate passes for the given context — the set to actually expose. */
export function enabledLocalTools(
  ctx: LocalToolCtx,
  meta: LocalToolGateMeta | undefined,
): LocalTool[] {
  return LOCAL_TOOLS.filter((t) => t.isEnabled(ctx, meta));
}
