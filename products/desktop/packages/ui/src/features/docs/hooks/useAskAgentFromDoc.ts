import type { Task } from "@posthog/shared/domain-types";
import { useAuthenticatedMutation } from "@posthog/ui/hooks/useAuthenticatedMutation";

const MAX_TITLE_LENGTH = 90;

/**
 * What a doc question runs on, with nothing to choose.
 *
 * A question about a page is not about a repository, so the run takes none. The
 * harness and the model are fixed: a doc answer has to arrive while the person
 * is still looking at the page, and a picker here would be one more decision for
 * no gain.
 */
export const DOC_AGENT_RUNTIME = "pi";
/** A cloud run needs an adapter even on the pi harness; the default one is Claude. */
export const DOC_AGENT_ADAPTER = "claude";
export const DOC_AGENT_MODEL = "zai-org/glm-5.3-flash";
export const DOC_AGENT_WORKSPACE_MODE = "cloud";

function toTitle(question: string): string {
  const trimmed = question.trim().replace(/\s+/g, " ");
  if (trimmed.length <= MAX_TITLE_LENGTH)
    return trimmed || "Question from a doc";
  return `${trimmed.slice(0, MAX_TITLE_LENGTH - 1).trimEnd()}…`;
}

/**
 * Asks the agent about something in a doc.
 *
 * The paragraph becomes a task in the space and goes straight to the agent, so
 * the conversation happens beside the doc instead of inside it. The agent never
 * edits the page: when the answer is worth keeping, the person puts it in.
 */
export function useAskAgentFromDoc(options: {
  channelId: string;
  docTitle: string;
}) {
  return useAuthenticatedMutation(
    async (client, variables: { question: string }): Promise<Task> => {
      const description = [
        variables.question.trim(),
        "",
        `Asked from the page "${options.docTitle}".`,
      ].join("\n");

      const task = await client.createTask({
        title: toTitle(variables.question),
        description,
        channel: options.channelId,
        runtime: DOC_AGENT_RUNTIME,
        model: DOC_AGENT_MODEL,
      });

      // Start the run with the question on it. A task with no run has nothing
      // to forward a message to, so creating and then sending would fail; this
      // one call starts the agent and gives it the question.
      return client.runTaskInCloud(task.id, null, {
        adapter: DOC_AGENT_ADAPTER,
        piRuntime: true,
        model: DOC_AGENT_MODEL,
        pendingUserMessage: variables.question.trim(),
      });
    },
  );
}
