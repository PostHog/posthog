import {
  runSignedMergeTool,
  SIGNED_MERGE_TOOL_DESCRIPTION,
  SIGNED_MERGE_TOOL_NAME,
  signedMergeToolSchema,
} from "../../signed-commit-shared";
import { defineSignedGitTool } from "./signed-git-tool";

export const signedMergeTool = defineSignedGitTool({
  name: SIGNED_MERGE_TOOL_NAME,
  description: SIGNED_MERGE_TOOL_DESCRIPTION,
  schema: signedMergeToolSchema,
  run: runSignedMergeTool,
});
