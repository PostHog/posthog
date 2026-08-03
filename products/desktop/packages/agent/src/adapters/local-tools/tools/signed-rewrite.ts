import {
  runSignedRewriteTool,
  SIGNED_REWRITE_TOOL_DESCRIPTION,
  SIGNED_REWRITE_TOOL_NAME,
  signedRewriteToolSchema,
} from "../../signed-commit-shared";
import { defineSignedGitTool } from "./signed-git-tool";

export const signedRewriteTool = defineSignedGitTool({
  name: SIGNED_REWRITE_TOOL_NAME,
  description: SIGNED_REWRITE_TOOL_DESCRIPTION,
  schema: signedRewriteToolSchema,
  run: runSignedRewriteTool,
});
