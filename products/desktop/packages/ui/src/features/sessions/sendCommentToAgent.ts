import { CommentToAgentService } from "@posthog/core/sessions/commentToAgent";
import { commentToAgentHost } from "./commentToAgentHost";

const commentToAgentService = new CommentToAgentService(commentToAgentHost);

export function sendCommentToAgent(
  input: Parameters<CommentToAgentService["send"]>[0],
): Promise<void> {
  return commentToAgentService.send(input);
}
