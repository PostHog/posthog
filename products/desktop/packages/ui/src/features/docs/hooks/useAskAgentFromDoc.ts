import { getCloudUrlFromRegion } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useAuthenticatedMutation } from "@posthog/ui/hooks/useAuthenticatedMutation";

const MAX_TITLE_LENGTH = 90;

function toTitle(question: string): string {
  const trimmed = question.trim().replace(/\s+/g, " ");
  if (trimmed.length <= MAX_TITLE_LENGTH)
    return trimmed || "Question from a doc";
  return `${trimmed.slice(0, MAX_TITLE_LENGTH - 1).trimEnd()}…`;
}

/**
 * Asks the agent about something in a doc.
 *
 * The question becomes a task in the space, and the conversation happens beside
 * the doc instead of inside it. The agent never edits the page: when the answer
 * is worth keeping, the person puts it in the doc.
 */
export function useAskAgentFromDoc(options: {
  channelId: string;
  docId: string;
  docTitle: string;
}) {
  const cloudRegion = useAuthStateValue((state) => state.cloudRegion);

  return useAuthenticatedMutation(
    (
      client,
      variables: { question: string; contextText: string },
    ): Promise<Task> => {
      const cloudUrl = cloudRegion ? getCloudUrlFromRegion(cloudRegion) : null;
      const link = cloudUrl
        ? `${cloudUrl.replace(/\/$/, "")}/code/docs/${options.channelId}/${options.docId}`
        : null;

      const description = [
        variables.question.trim(),
        "",
        "From this part of the doc:",
        variables.contextText.trim(),
        "",
        `Doc: "${options.docTitle}".`,
        link,
      ]
        .filter((part) => part !== null)
        .join("\n");

      return client.createTask({
        title: toTitle(variables.question),
        description,
        channel: options.channelId,
        pending_user_message: variables.question.trim(),
      });
    },
  );
}
