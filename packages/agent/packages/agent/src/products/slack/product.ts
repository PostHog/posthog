import {
  isBenjaminEnabled,
  SIMPLIFIED_TECHNICAL_ENGLISH_INSTRUCTION,
} from "@posthog/harness/extensions/benjamin";
import { z } from "zod";
import type {
  AgentProduct,
  Question,
  QuestionRequest,
} from "../../sdk/product";
import { buildPullRequestFooter, defineProduct } from "../../sdk/product";
import {
  buildSlackDeliveryInstructions,
  buildSlackIdentityInstructions,
  type SlackPromptOptions,
} from "./prompt";

const SLACK_ORIGIN = "slack";

const AWAITING_REPLY_MESSAGE =
  "This question has been relayed to the Slack thread where this task originated. " +
  "The user will reply there. Do NOT re-ask the question or pick an answer yourself. " +
  "Simply let the user know you are waiting for their reply.";

const slackLaunchOptionsSchema = z.object({
  slack_reply_context: z.boolean().catch(false),
  // The backend resolves delivery routes from flags and Slack scopes. An unset key means it
  // told us nothing, so emit no constraints rather than offer a route delivery would reject.
  slack_artifact_delivery: z
    .enum(["none", "message", "canvas_file"])
    .nullable()
    .catch(null),
  // Charts need only the rollout flag, while canvas and file delivery also need Slack
  // scopes, so a workspace can have charts and nothing else.
  slack_chart_delivery: z.boolean().catch(false),
  slack_chart_links: z.boolean().catch(false),
  slack_app_agent_design_enabled: z.boolean().catch(false),
  slack_thread_url: z.string().nullable().catch(null),
  slack_notified_pr_url: z.string().nullable().catch(null),
  client_platform: z.string().optional().catch(undefined),
});

export function isSlackLaunch(
  originProduct: string | undefined,
  launchOptions: Record<string, unknown>,
): boolean {
  if (originProduct === SLACK_ORIGIN) {
    return true;
  }
  return Object.entries(launchOptions).some(
    ([key, value]) => key.startsWith("slack_") && Boolean(value),
  );
}

function formatQuestion(question: Question): string {
  let message = `*${question.question}*\n\n`;
  for (const [index, option] of (question.options ?? []).entries()) {
    message += `${index + 1}. *${option.label}*`;
    if (option.description) {
      message += ` — ${option.description}`;
    }
    message += "\n";
  }
  message += "\nReply in this thread with your choice.";
  return message;
}

export function slackProduct(): AgentProduct {
  return defineProduct({
    id: SLACK_ORIGIN,
    launchOptionsSchema: slackLaunchOptionsSchema,
    configureSession({ launch, services }) {
      const { launchOptions } = launch;
      const slackOrigin = launch.originProduct === SLACK_ORIGIN;
      const slackReply = slackOrigin || launchOptions.slack_reply_context;
      const promptOptions: SlackPromptOptions = {
        slackArtifactDelivery: launchOptions.slack_artifact_delivery,
        // The backend keeps chart delivery on next to the links key, so an older agent image
        // still posts images while this one prefers the link.
        slackCharts: launchOptions.slack_chart_links
          ? "link"
          : launchOptions.slack_chart_delivery
            ? "image"
            : null,
        slackProgressChecklist: launchOptions.slack_app_agent_design_enabled,
      };
      const threadUrl = launchOptions.slack_thread_url;
      const footerSource = threadUrl
        ? { label: "Slack thread", url: threadUrl }
        : launch.source;
      const closingInstructions =
        slackReply && isBenjaminEnabled()
          ? SIMPLIFIED_TECHNICAL_ENGLISH_INSTRUCTION
          : undefined;

      const handleQuestions = ({ questions }: QuestionRequest) => {
        const question = questions[0];
        if (question) {
          void services.sendReply({ message: formatQuestion(question) });
        }
        return {
          message: AWAITING_REPLY_MESSAGE,
          awaitingReply: Boolean(question),
        };
      };

      return {
        identityInstructions: slackReply
          ? buildSlackIdentityInstructions(promptOptions)
          : undefined,
        deliveryInstructions: buildSlackDeliveryInstructions(promptOptions),
        closingInstructions,
        replySurface: slackReply ? SLACK_ORIGIN : undefined,
        pullRequests: {
          autoPublish: slackOrigin,
          existingUrl: launchOptions.slack_notified_pr_url,
          footer: buildPullRequestFooter(launch, {
            automated: slackOrigin,
            source: footerSource,
          }),
        },
        handleQuestions: slackOrigin ? handleQuestions : undefined,
      };
    },
  });
}
