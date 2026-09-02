import { getCloudUrlFromRegion } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useAuthenticatedMutation } from "@posthog/ui/hooks/useAuthenticatedMutation";

/** A task title reads better short; the whole line still goes in the description. */
const MAX_TITLE_LENGTH = 90;

function toTitle(line: string): string {
  const trimmed = line.trim().replace(/\s+/g, " ");
  if (trimmed.length <= MAX_TITLE_LENGTH) return trimmed || "Work from a doc";
  return `${trimmed.slice(0, MAX_TITLE_LENGTH - 1).trimEnd()}…`;
}

/**
 * Starts a task from a line in a doc.
 *
 * The task is created directly, with the line and a link back to the doc in its
 * description. Nothing reads or rewrites the line: the doc keeps only the task
 * id, and the chip reads the rest live.
 */
export function useCreateTaskFromDoc(options: {
  channelId: string;
  docId: string;
  docTitle: string;
}) {
  const cloudRegion = useAuthStateValue((state) => state.cloudRegion);

  return useAuthenticatedMutation(
    (client, variables: { lineText: string }): Promise<Task> => {
      const cloudUrl = cloudRegion ? getCloudUrlFromRegion(cloudRegion) : null;
      const link = cloudUrl
        ? `${cloudUrl.replace(/\/$/, "")}/code/docs/${options.channelId}/${options.docId}`
        : null;

      const description = [
        variables.lineText.trim(),
        "",
        `From the doc "${options.docTitle}".`,
        link,
      ]
        .filter((part) => part !== null)
        .join("\n");

      return client.createTask({
        title: toTitle(variables.lineText),
        description,
        channel: options.channelId,
        origin_product: "docs",
      });
    },
  );
}
