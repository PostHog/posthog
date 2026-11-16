import { SIMPLIFIED_TECHNICAL_ENGLISH_INSTRUCTION } from "@posthog/harness/extensions/benjamin";
import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  ProductServices,
  QuestionRequest,
  SessionBehavior,
} from "../../sdk/product";
import { slackProduct } from "./product";

const question: QuestionRequest = {
  questions: [
    {
      question: "Which license?",
      options: [{ label: "MIT", description: "Permissive" }],
    },
    { question: "Which branch?" },
  ],
};

async function configure(
  launchOptions: Record<string, unknown>,
  originProduct?: string,
  services: ProductServices = {
    sendReply: vi.fn().mockResolvedValue(undefined),
  },
): Promise<SessionBehavior> {
  return slackProduct().configureSession({
    launch: { taskId: "task-1", runId: "run-1", originProduct, launchOptions },
    services,
  });
}

describe("Slack product", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  // Charts need only the rollout flag, while canvas/file also needs Slack scopes still in
  // review, so the chart offer has to be independent of the delivery mode in both
  // directions: present on a message-only workspace, absent on a canvas_file one whose
  // backend never sent the key.
  it.each([
    [null, false],
    [null, true],
    ["none", false],
    ["none", true],
    ["message", false],
    ["message", true],
    ["canvas_file", false],
    ["canvas_file", true],
  ] as const)(
    "offers only supported delivery routes (delivery: %s, charts: %s)",
    async (delivery, charts) => {
      const { deliveryInstructions = "" } = await configure({
        slack_artifact_delivery: delivery,
        slack_chart_delivery: charts,
      });
      const supportsArtifacts =
        delivery === "message" || delivery === "canvas_file";

      expect(deliveryInstructions.includes("## Delivering to Slack")).toBe(
        delivery !== null,
      );
      expect(
        deliveryInstructions.includes(
          "You do not have artifact delivery in this workspace",
        ),
      ).toBe(delivery === "none");
      expect(
        deliveryInstructions.includes(
          "You do not have canvas or file delivery",
        ),
      ).toBe(delivery === "message");
      expect(
        deliveryInstructions.includes(
          "`slack_canvas`, `slack_message`, `slack_file`",
        ),
      ).toBe(delivery === "canvas_file");
      expect(deliveryInstructions.includes("living_artifacts/chart/")).toBe(
        supportsArtifacts && charts,
      );
      // Without this the two bullets contradict each other: one forbids file delivery, the
      // other tells the agent to deliver an image.
      expect(
        deliveryInstructions.includes("Chart images are the one exception"),
      ).toBe(delivery === "message" && charts);
      expect(deliveryInstructions.includes("insights/new#q=")).toBe(false);
    },
  );

  // The backend sends both keys when links are on, and the chart endpoint has to leave the
  // prompt with the link guidance in every delivery mode.
  it.each(["none", "message", "canvas_file"] as const)(
    "tells a %s workspace to share an insight link instead of a chart image when links are on",
    async (delivery) => {
      const { deliveryInstructions = "" } = await configure({
        slack_artifact_delivery: delivery,
        slack_chart_delivery: true,
        slack_chart_links: true,
      });

      expect(deliveryInstructions).toContain("insights/new#q=<query>");
      expect(deliveryInstructions).toContain("the only PostHog link");
      expect(deliveryInstructions).not.toContain("living_artifacts/chart/");
    },
  );

  it.each([
    ["slack", {}, true],
    ["workflow", { slack_reply_context: true }, true],
    ["workflow", { slack_thread_url: "https://example.com/t" }, false],
  ] as const)(
    "uses the Slack reply style only for Slack replies (origin: %s, %o)",
    async (origin, launchOptions, slackReply) => {
      vi.stubEnv("POSTHOG_BENJAMIN", "1");
      const session = await configure(launchOptions, origin);

      expect(
        (session.identityInstructions ?? "").includes("PostHog Slack app"),
      ).toBe(slackReply);
      expect(session.replySurface).toBe(slackReply ? "slack" : undefined);
      expect(session.closingInstructions).toBe(
        slackReply ? SIMPLIFIED_TECHNICAL_ENGLISH_INSTRUCTION : undefined,
      );
    },
  );

  it.each([false, true])(
    "asks for a task list only when the checklist is visible: %s",
    async (checklist) => {
      // The checklist is the Slack progress UI. Without it the task list is invisible,
      // and asking for one only costs the agent turns.
      const session = await configure(
        { slack_app_agent_design_enabled: checklist },
        "slack",
      );

      expect(
        session.identityInstructions?.includes("# Progress checklist"),
      ).toBe(checklist);
    },
  );

  it.each([
    [
      "slack",
      { slack_thread_url: "https://example.com/t" },
      true,
      "*Created with [PostHog](https://posthog.com?ref=pr) from a [Slack thread](https://example.com/t)*",
    ],
    [
      "workflow",
      { slack_reply_context: true },
      false,
      "*Created with [PostHog Desktop](https://posthog.com/desktop?ref=pr)*",
    ],
  ] as const)(
    "publishes only for the Slack app origin (origin: %s)",
    async (origin, launchOptions, autoPublish, footer) => {
      const session = await configure(launchOptions, origin);

      expect(session.pullRequests).toEqual({
        autoPublish,
        existingUrl: null,
        footer,
      });
    },
  );

  it("keeps defaults for malformed launch options", async () => {
    const session = await configure(
      {
        slack_artifact_delivery: "unknown",
        slack_chart_delivery: "true",
        slack_app_agent_design_enabled: 1,
        slack_thread_url: 123,
        slack_notified_pr_url: [],
      },
      "slack",
    );

    expect(session.deliveryInstructions).toBe("");
    expect(session.identityInstructions).not.toContain("# Progress checklist");
    expect(session.pullRequests?.existingUrl).toBeNull();
  });

  it.each([
    {
      name: "relays the first question and asks the agent to wait",
      request: question,
      relayed: true,
    },
    {
      name: "asks the agent to wait without a relay for invalid question data",
      request: { questions: [] },
      relayed: false,
    },
  ])("$name", async ({ request, relayed }) => {
    const sendReply = vi.fn().mockResolvedValue(undefined);
    const session = await configure({}, "slack", { sendReply });

    const response = session.handleQuestions?.(request);

    expect(response).toEqual({
      message: expect.stringContaining("relayed to the Slack thread"),
      awaitingReply: relayed,
    });
    if (relayed) {
      expect(sendReply).toHaveBeenCalledExactlyOnceWith({
        message:
          "*Which license?*\n\n1. *MIT* — Permissive\n\nReply in this thread with your choice.",
      });
    } else {
      expect(sendReply).not.toHaveBeenCalled();
    }
  });

  it("leaves questions to the default flow outside the Slack app", async () => {
    const session = await configure({ slack_reply_context: true }, "workflow");

    expect(session.handleQuestions).toBeUndefined();
  });
});
