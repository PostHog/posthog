import { describe, expect, it } from "vitest";
import {
  type ArtifactRow,
  commentSources,
  commentTargets,
} from "./taskArtifactRows";

describe("commentSources", () => {
  it("makes reference rows commentable, agreeing with commentTargets", () => {
    const row: ArtifactRow = {
      kind: "posthog_object",
      key: "posthog-object:art-1",
      artifactId: "art-1",
      name: "Checkout funnel",
      runId: "run-1",
      metadata: {
        reference_type: "posthog_object",
        object_kind: "insight",
        object_id: "9pQx3",
        source_message_ids: ["msg-1"],
        occurrence_count: 1,
      },
      uploadedAt: undefined,
    };

    const referenceSource = commentSources("task-1", [row]).find(
      (source) => source.kind === "posthog_object",
    );

    expect(referenceSource).toEqual({
      kind: "posthog_object",
      target: { scope: "task_artifact", itemId: "art-1" },
      name: "Checkout funnel",
      runId: "run-1",
    });
    // The Artifacts pane badge (commentTargets) and the Comments pane
    // (commentSources) must agree on which resources can hold threads.
    expect(commentTargets([row])).toContainEqual(referenceSource?.target);
  });
});
