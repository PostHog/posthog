import type { Task, TaskRun } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import {
  type ArtifactRow,
  buildRows,
  commentSources,
  commentTargets,
  orderRows,
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
});

describe("orderRows", () => {
  it("keeps pull requests first and puts the newest artifact on top", () => {
    const file = (name: string, uploadedAt: string): ArtifactRow =>
      ({
        kind: "file",
        key: `file:${name}`,
        artifactId: name,
        name,
        runId: "run-1",
        size: undefined,
        group: { name, latest: { uploaded_at: uploadedAt }, versions: [] },
      }) as unknown as ArtifactRow;
    const rows: ArtifactRow[] = [
      { kind: "slack", key: "slack-thread", url: "https://example.com" },
      file("old.html", "2026-08-01T00:00:00Z"),
      { kind: "pr", key: "pr-old", url: "https://example.com/1", ts: 1 },
      file("new.png", "2026-08-03T00:00:00Z"),
      { kind: "pr", key: "pr-new", url: "https://example.com/2", ts: 2 },
      {
        kind: "canvas",
        key: "canvas",
        name: "Board",
        url: null,
        dashboardId: null,
        ts: Date.parse("2026-08-02T00:00:00Z"),
      },
    ];

    const { pullRequests, others } = orderRows(rows);

    expect(pullRequests.map((row) => row.key)).toEqual(["pr-new", "pr-old"]);
    expect(others.map((row) => row.key)).toEqual([
      "file:new.png",
      "canvas",
      "file:old.html",
      "slack-thread",
    ]);
  });
});
