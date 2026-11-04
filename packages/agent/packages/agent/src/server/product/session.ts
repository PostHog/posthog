import { z } from "zod";
import type { PostHogAPIClient } from "../../posthog-api";
import {
  buildPullRequestFooter,
  type ProductLaunchConfiguration,
  type ProductSelector,
  type QuestionRequest,
  type SessionBehavior,
} from "../../sdk/product";

type SystemPrompt = string | { append: string };

const questionSchema = z.object({
  question: z.string(),
  options: z
    .array(
      z.object({
        label: z.string(),
        description: z.string().optional().catch(undefined),
      }),
    )
    .optional(),
});

export async function openProductSession(
  selectProduct: ProductSelector | undefined,
  launch: ProductLaunchConfiguration,
  api: Pick<PostHogAPIClient, "relayMessage">,
  reportFailure: (message: string, error: unknown) => void,
): Promise<SessionBehavior> {
  const product = selectProduct?.(launch);
  if (!product) {
    return {};
  }
  return product.configureSession({
    launch,
    services: {
      sendReply: (reply) =>
        api
          .relayMessage(launch.taskId, launch.runId, reply.message)
          .catch((error) => reportFailure("Failed to send a reply", error)),
    },
  });
}

export function resolvePullRequestFooter(
  session: SessionBehavior,
  launch: ProductLaunchConfiguration,
): string {
  return (
    session.pullRequests?.footer ??
    buildPullRequestFooter(launch, { source: launch.source })
  );
}

export function appendClosingInstructions(
  prompt: SystemPrompt,
  session: SessionBehavior,
): SystemPrompt {
  const closing = session.closingInstructions;
  if (!closing) {
    return prompt;
  }
  const text = typeof prompt === "string" ? prompt : prompt.append;
  const combined = [text, closing].filter(Boolean).join("\n\n");
  return typeof prompt === "string" ? combined : { append: combined };
}

export function readQuestionRequest(questions: unknown): QuestionRequest {
  const firstQuestion = Array.isArray(questions) ? questions[0] : undefined;
  const parsed = questionSchema.safeParse(firstQuestion);
  return { questions: parsed.success ? [parsed.data] : [] };
}
