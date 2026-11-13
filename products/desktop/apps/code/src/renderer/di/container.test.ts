import { WARM_TASK_SERVICE } from "@posthog/core/task-detail/warmTaskService";
import { expect, test, vi } from "vitest";
import { container } from "./container";
import "../desktop-services";

vi.hoisted(() => {
  Object.assign(globalThis, {
    electronTRPC: { sendMessage: vi.fn(), onMessage: vi.fn() },
  });
});

test("the desktop composer can acquire a draft with warming disabled", () => {
  const draft = container
    .get(WARM_TASK_SERVICE)
    .draft("test-account", "test-draft");
  draft.update(null, null);
  const submission = draft.beginSubmission();
  expect(submission?.take({})).toBeNull();
  submission?.finish(false);
});
