import { describe, expect, it } from "vitest";
import {
  normalizeTaskResponse,
  normalizeTaskRunResponse,
} from "./task-normalization";

describe("task response normalization", () => {
  it("normalizes legacy started runs and nullable generated fields", () => {
    expect(
      normalizeTaskRunResponse(
        {
          id: "run-1",
          task: "task-1",
          status: "started",
          branch: null,
          stage: null,
          runtime_adapter: null,
          model: null,
          reasoning_effort: null,
          log_url: null,
          error_message: null,
          output: null,
          state: null,
          artifacts: [
            {
              id: "artifact-1",
              name: "result.txt",
              type: "legacy_type",
              storage_path: "tasks/result.txt",
              uploaded_at: "2026-07-21T00:00:00Z",
              uploaded_by: "user",
              uploaded_by_user_id: 42,
            },
          ],
          created_at: "2026-07-21T00:00:00Z",
          updated_at: "2026-07-21T00:01:00Z",
          completed_at: null,
        },
        { teamId: 123 },
      ),
    ).toEqual({
      id: "run-1",
      task: "task-1",
      team: 123,
      branch: null,
      stage: null,
      runtime_adapter: null,
      model: null,
      reasoning_effort: null,
      status: "in_progress",
      log_url: "",
      error_message: null,
      output: null,
      state: {},
      artifacts: [
        {
          id: "artifact-1",
          name: "result.txt",
          type: "artifact",
          storage_path: "tasks/result.txt",
          uploaded_at: "2026-07-21T00:00:00Z",
          uploaded_by: "user",
          uploaded_by_user_id: 42,
        },
      ],
      created_at: "2026-07-21T00:00:00Z",
      updated_at: "2026-07-21T00:01:00Z",
      completed_at: null,
    });
  });

  it("keeps PostHog reference metadata without requiring file storage", () => {
    expect(
      normalizeTaskRunResponse(
        {
          id: "run-1",
          artifacts: [
            {
              id: "phref-1",
              name: "Checkout funnel",
              type: "reference",
              source: "posthog_object",
              uploaded_at: "2026-08-19T00:00:00Z",
              metadata: {
                reference_type: "posthog_object",
                object_kind: "insight",
                object_id: "9pQx3",
                source_message_ids: ["turn-1"],
                occurrence_count: 1,
              },
            },
          ],
        },
        { teamId: 123, taskId: "task-1" },
      ).artifacts,
    ).toEqual([
      {
        id: "phref-1",
        name: "Checkout funnel",
        type: "reference",
        source: "posthog_object",
        uploaded_at: "2026-08-19T00:00:00Z",
        metadata: {
          reference_type: "posthog_object",
          object_kind: "insight",
          object_id: "9pQx3",
          source_message_ids: ["turn-1"],
          occurrence_count: 1,
        },
      },
    ]);
  });

  it("normalizes task responses and their generated latest-run records", () => {
    expect(
      normalizeTaskResponse(
        {
          id: "task-1",
          task_number: null,
          slug: "task-1",
          repository: null,
          github_integration: null,
          github_user_integration: null,
          json_schema: null,
          signal_report: null,
          channel: null,
          latest_run: {
            id: "run-1",
            status: "started",
            log_url: null,
          },
          created_at: "2026-07-21T00:00:00Z",
          updated_at: "2026-07-21T00:01:00Z",
        },
        { teamId: 123 },
      ),
    ).toMatchObject({
      id: "task-1",
      task_number: null,
      slug: "task-1",
      title: "",
      description: "",
      origin_product: "",
      repository: null,
      github_integration: null,
      github_user_integration: null,
      json_schema: null,
      signal_report: null,
      channel: null,
      latest_run: {
        id: "run-1",
        task: "task-1",
        team: 123,
        status: "in_progress",
        log_url: "",
        output: null,
        state: {},
      },
    });
  });

  // Multi-repo handoff and cloud-run instructions read task.repositories, so
  // dropping this fallback silently degrades every consumer to single-repo.
  it.each([
    [
      "keeps the API's repositories list",
      { repository: "posthog/posthog", repositories: ["a/b", "c/d"] },
      ["a/b", "c/d"],
    ],
    [
      "wraps a lone repository",
      { repository: "posthog/posthog" },
      ["posthog/posthog"],
    ],
    ["defaults to empty", {}, []],
  ])("populates repositories (%s)", (_label, dto, expected) => {
    expect(
      normalizeTaskResponse({ id: "task-1", ...dto }, { teamId: 1 })
        .repositories,
    ).toEqual(expected);
  });
});
