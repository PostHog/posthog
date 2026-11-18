import { CommentToAgentService } from "@posthog/core/sessions/commentToAgent";
import { toast } from "@posthog/ui/primitives/toast";
import { commentToAgentHost } from "./commentToAgentHost";

const commentToAgentService = new CommentToAgentService(commentToAgentHost);

export function sendCommentToAgent(
  input: Parameters<CommentToAgentService["send"]>[0],
): Promise<void> {
  return commentToAgentService.send(input).catch(() => {
    toast.error(
      "Couldn't add the comment to chat",
      "Your comment is saved. Copy it into the chat to send it to the agent.",
    );
  });
}
