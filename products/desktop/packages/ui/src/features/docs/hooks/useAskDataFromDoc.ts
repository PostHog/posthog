import type { Task } from "@posthog/shared/domain-types";
import { useMutation } from "@tanstack/react-query";
import { dataPointTaskInput } from "./docThreadPrompt";
import { useDocAgentRun } from "./useDocAgentRun";

/**
 * Asks the agent for a data point from inside a page.
 *
 * The page keeps the request where it will sit, so the reader stays on the
 * page while the agent looks. The answer never travels through prose: the agent
 * hands the query in with a tool or ends as the schema's JSON, and the page
 * reads it off the thread.
 */
export function useAskDataFromDoc(options: {
  channelId: string;
  docTitle: string;
}) {
  const run = useDocAgentRun({ channelId: options.channelId });

  return useMutation({
    mutationFn: async (variables: {
      question: string;
      requestId: string;
    }): Promise<Task> => {
      const input = dataPointTaskInput({
        ...variables,
        docTitle: options.docTitle,
      });
      return run({
        question: input.question,
        titleFallback: "Data for a page",
        description: input.description,
      });
    },
  });
}
