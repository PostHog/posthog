import { describe, expect, it } from "vitest";
import {
  buildSlashFeedbackEvents,
  buildTurnRatingMetric,
  type SlashFeedbackInput,
} from "./aiFeedback";

const run = { taskId: "task-1", taskRunId: "run-1" };

const context = {
  $ai_session_id: "task-1",
  $ai_trace_id: null,
  ai_product: "posthog_code",
  task_id: "task-1",
  task_run_id: "run-1",
};

describe("aiFeedback", () => {
  it.each([
    ["positive", "good"],
    ["negative", "bad"],
  ] as const)(
    "maps a %s thumb to a quality=%s metric on the turn",
    (sentiment, rating) => {
      expect(
        buildTurnRatingMetric({ run, turnId: "turn-9", sentiment }),
      ).toEqual({
        ...context,
        turn_id: "turn-9",
        $ai_metric_name: "quality",
        $ai_metric_value: rating,
      });
    },
  );

  it("still rates a turn when the thread has no task", () => {
    expect(
      buildTurnRatingMetric({
        run: { taskId: null },
        turnId: "turn-1",
        sentiment: "positive",
      }),
    ).toMatchObject({
      $ai_session_id: null,
      task_id: null,
      task_run_id: undefined,
      $ai_metric_value: "good",
    });
  });

  it.each<
    [
      string,
      Pick<SlashFeedbackInput, "feedbackType" | "comment">,
      { rating: "good" | "bad" | null; text: string | null },
    ]
  >([
    ["/good", { feedbackType: "good" }, { rating: "good", text: null }],
    [
      "/bad with a comment",
      { feedbackType: "bad", comment: "  wrong file  " },
      { rating: "bad", text: "wrong file" },
    ],
    [
      "/feedback with a comment",
      { feedbackType: "general", comment: "add a diff view" },
      { rating: null, text: "add a diff view" },
    ],
    [
      "/feedback with no comment",
      { feedbackType: "general" },
      { rating: null, text: null },
    ],
    [
      "/good with a blank comment",
      { feedbackType: "good", comment: "   " },
      { rating: "good", text: null },
    ],
  ])("%s", (_label, input, expected) => {
    const { metric, feedback } = buildSlashFeedbackEvents({
      run,
      eventCount: 12,
      ...input,
    });
    const slashContext = {
      ...context,
      feedback_type: input.feedbackType,
      event_count: 12,
    };
    expect(metric).toEqual(
      expected.rating === null
        ? null
        : {
            ...slashContext,
            $ai_metric_name: "quality",
            $ai_metric_value: expected.rating,
          },
    );
    expect(feedback).toEqual(
      expected.text === null
        ? null
        : { ...slashContext, $ai_feedback_text: expected.text },
    );
  });
});
