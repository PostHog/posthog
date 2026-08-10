import {
  runSignedCommitTool,
  SIGNED_COMMIT_TOOL_DESCRIPTION,
  SIGNED_COMMIT_TOOL_NAME,
  signedCommitToolSchema,
} from "../../signed-commit-shared";
import { defineSignedGitTool } from "./signed-git-tool";

export const signedCommitTool = defineSignedGitTool({
  name: SIGNED_COMMIT_TOOL_NAME,
  description: SIGNED_COMMIT_TOOL_DESCRIPTION,
  schema: signedCommitToolSchema,
  run: runSignedCommitTool,
});
