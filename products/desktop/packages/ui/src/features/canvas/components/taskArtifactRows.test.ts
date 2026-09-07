import type { DashboardRecord } from "@posthog/core/canvas/dashboardSchemas";
import type { Task, TaskRun } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import {
  type ArtifactRow,
  buildRows,
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

describe("buildRows", () => {
  it("counts a reference cited by several runs across the whole task", () => {
    const reference = (uploadedAt: string, messageIds: string[]) => ({
      id: "phref-1",
      name: "Checkout funnel",
      type: "reference",
      uploaded_at: uploadedAt,
      metadata: {
        reference_type: "posthog_object",
        object_kind: "insight",
        object_id: "9pQx3",
        source_message_ids: messageIds,
        occurrence_count: messageIds.length,
      },
    });
    const runs = [
      {
        id: "run-1",
        updated_at: "2026-08-01T00:00:00Z",
        artifacts: [reference("2026-08-01T00:00:00Z", ["msg-1", "msg-2"])],
      },
      {
        id: "run-2",
        updated_at: "2026-08-02T00:00:00Z",
        artifacts: [reference("2026-08-02T00:00:00Z", ["msg-2", "msg-3"])],
      },
    ] as unknown as TaskRun[];

    const rows = buildRows({ id: "task-1" } as Task, [], runs).filter(
      (row) => row.kind === "posthog_object",
    );

    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      runId: "run-2",
      metadata: {
        source_message_ids: ["msg-1", "msg-2", "msg-3"],
        occurrence_count: 3,
      },
    });
  });

  it("lists a canvas the thread never announced, once", () => {
    const canvas = {
      id: "canvas-1",
      channelId: "channel-1",
      name: "Weather board",
      createdAt: 1_700_000_000_000,
    } as DashboardRecord;
    const announced = [
      {
        kind: "artifact" as const,
        timestamp: 1_700_000_001_000,
        message: { id: "msg-1" },
        artifact: {
          kind: "canvas" as const,
          name: "Weather board",
          url: "https://us.posthog.com/code/canvas/channel-1/canvas-1",
        },
      },
    ] as Parameters<typeof buildRows>[1];

    const silent = buildRows({ id: "task-1" } as Task, [], [], [canvas]).filter(
      (row) => row.kind === "canvas",
    );
    const alsoAnnounced = buildRows(
      { id: "task-1" } as Task,
      announced,
      [],
      [canvas],
    ).filter((row) => row.kind === "canvas");

    expect(silent).toMatchObject([
      { name: "Weather board", dashboardId: "canvas-1" },
    ]);
    // The announcement already carries the canvas; the record must not add a
    // second row for it.
    expect(alsoAnnounced).toMatchObject([{ key: "msg-1" }]);
  });
});
