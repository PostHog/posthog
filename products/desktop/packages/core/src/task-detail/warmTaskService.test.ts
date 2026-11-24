import {
  afterEach,
  assert,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import {
  type WarmTaskClient,
  type WarmTaskOptions,
  WarmTaskService,
} from "./warmTaskService";

const options: WarmTaskOptions = {
  repository: "example/project",
  github_integration: 1,
  branch: "main",
  runtime_adapter: "claude",
  initial_permission_mode: "plan",
};
const warm = { task_id: "warm-task", run_id: "warm-run" };
const lease = { taskId: warm.task_id, runId: warm.run_id };
const log = { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() };

function setup() {
  const client = {
    warmTask: vi.fn<WarmTaskClient["warmTask"]>().mockResolvedValue(warm),
    cancelTaskRun: vi
      .fn<WarmTaskClient["cancelTaskRun"]>()
      .mockResolvedValue({}),
  };
  const service = new WarmTaskService({ ...log, scope: () => log });
  const draft = service.draft("account:project", "composer");
  return { client, service, draft };
}

describe("warm task drafts", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("debounces the latest selection and applies current reasoning effort", async () => {
    const { client, draft } = setup();
    draft.update(options, client);
    await vi.advanceTimersByTimeAsync(300);
    draft.update({ ...options, branch: "feature" }, client);
    draft.update(
      { ...options, branch: "feature", reasoning_effort: "high" },
      client,
    );
    await vi.advanceTimersByTimeAsync(600);
    expect(client.warmTask).toHaveBeenCalledExactlyOnceWith({
      ...options,
      branch: "feature",
      reasoning_effort: "high",
    });
  });

  it.each([
    { mutable: true, late: false },
    { mutable: true, late: true },
    { mutable: false, late: false },
    { mutable: false, late: true },
  ])(
    "negotiates permission-only changes with server support: %j",
    async ({ mutable, late }) => {
      const { client, draft } = setup();
      const response = { ...warm, permission_mode_mutable: mutable };
      const pending = Promise.withResolvers<typeof response>();
      client.warmTask.mockReturnValueOnce(
        late ? pending.promise : Promise.resolve(response),
      );
      draft.update(options, client);
      await vi.advanceTimersByTimeAsync(600);
      const changed = {
        ...options,
        initial_permission_mode: "default" as const,
      };
      draft.update(changed, client);
      if (late) pending.resolve(response);
      await vi.advanceTimersByTimeAsync(600);
      expect(client.warmTask).toHaveBeenCalledTimes(1);
      const submission = draft.beginSubmission();
      expect(submission?.take(changed)).toEqual(
        mutable ? { ...lease, permissionModeMutable: true } : null,
      );
      submission?.finish(true, warm.task_id);
      expect(client.cancelTaskRun).toHaveBeenCalledTimes(mutable ? 0 : 1);
    },
  );

  it.each([
    { repository: "example/other" },
    { github_integration: 2 },
    { branch: "feature" },
    { runtime_adapter: "codex" },
    { model: "other" },
    { sandbox_environment_id: "other" },
    { custom_image_id: "other" },
  ])(
    "keeps non-permission settings strict with a mutable mode: %j",
    async (change) => {
      const { client, draft } = setup();
      client.warmTask.mockResolvedValue({
        ...warm,
        permission_mode_mutable: true,
      });
      draft.update(options, client);
      await vi.advanceTimersByTimeAsync(600);
      const changed = { ...options, ...change };
      draft.update(changed, client);
      await vi.advanceTimersByTimeAsync(600);
      expect(draft.beginSubmission()?.take(changed)).toBeNull();
      expect(client.warmTask).toHaveBeenCalledTimes(1);
      expect(client.cancelTaskRun).toHaveBeenCalledExactlyOnceWith(
        warm.task_id,
        warm.run_id,
        undefined,
        true,
      );
    },
  );

  it.each([
    { initial_permission_mode: "default" as const },
    { repository: "example/other" },
    { repositories: ["example/project", "example/other"] },
    { github_integration: 2 },
    { branch: "feature" },
    { runtime_adapter: "codex" },
    { model: "different" },
    { sandbox_environment_id: "different" },
    { custom_image_id: "different" },
  ])(
    "releases incompatible warms without replenishing the budget: %j",
    async (change) => {
      const { client, draft, service } = setup();
      draft.update(options, client);
      await vi.advanceTimersByTimeAsync(600);
      draft.update({ ...options, ...change }, client);
      await vi.advanceTimersByTimeAsync(600);
      const remounted = service.draft("account:project", "composer");
      remounted.update(options, client);
      await vi.advanceTimersByTimeAsync(600);
      expect(client.warmTask).toHaveBeenCalledTimes(1);
      expect(client.cancelTaskRun).toHaveBeenCalledExactlyOnceWith(
        warm.task_id,
        warm.run_id,
        undefined,
        true,
      );
      expect(remounted.beginSubmission()?.take(options)).toBeNull();
    },
  );

  it("releases a late response after the selection changes", async () => {
    const { client, draft } = setup();
    const pending = Promise.withResolvers<typeof warm>();
    client.warmTask.mockReturnValueOnce(pending.promise);
    draft.update(options, client);
    await vi.advanceTimersByTimeAsync(600);
    draft.update({ ...options, initial_permission_mode: "default" }, client);
    pending.resolve(warm);
    await vi.advanceTimersByTimeAsync(600);
    expect(client.warmTask).toHaveBeenCalledTimes(1);
    expect(client.cancelTaskRun).toHaveBeenCalledExactlyOnceWith(
      warm.task_id,
      warm.run_id,
      undefined,
      true,
    );
    expect(draft.beginSubmission()?.take(options)).toBeNull();
  });

  it.each([false, true])(
    "releases abandoned drafts including late responses (late: %s)",
    async (late) => {
      const { client, draft } = setup();
      let resolve!: (value: typeof warm) => void;
      if (late)
        client.warmTask.mockReturnValueOnce(
          new Promise((done) => {
            resolve = done;
          }),
        );
      const detach = draft.attach();
      draft.update(options, client);
      await vi.advanceTimersByTimeAsync(600);
      detach();
      await vi.advanceTimersByTimeAsync(0);
      if (late) resolve(warm);
      await vi.advanceTimersByTimeAsync(0);
      expect(client.cancelTaskRun).toHaveBeenCalledExactlyOnceWith(
        warm.task_id,
        warm.run_id,
        undefined,
        true,
      );
    },
  );

  it("hands off before cleanup, rejects double submission, and renews the budget only after success", async () => {
    const { client, draft } = setup();
    const detach = draft.attach();
    draft.update(options, client);
    await vi.advanceTimersByTimeAsync(600);
    const submission = draft.beginSubmission();
    assert(submission);
    expect(draft.beginSubmission()).toBeNull();
    detach();
    draft.update(null, null);
    await vi.advanceTimersByTimeAsync(0);
    expect(submission.take({ ...options, reasoning_effort: "high" })).toEqual(
      lease,
    );
    expect(submission.take(options)).toBeNull();
    submission.finish(true, lease.taskId);
    expect(client.cancelTaskRun).not.toHaveBeenCalled();
    draft.update(options, client);
    await vi.advanceTimersByTimeAsync(600);
    expect(client.warmTask).toHaveBeenCalledTimes(2);
  });

  it.each(["submit", "failure", "mismatch", "cold fallback"])(
    "releases unused runs during %s",
    async (reason) => {
      const { client, draft } = setup();
      let resolve!: (value: typeof warm) => void;
      if (reason === "submit")
        client.warmTask.mockReturnValueOnce(
          new Promise((done) => {
            resolve = done;
          }),
        );
      draft.update(options, client);
      await vi.advanceTimersByTimeAsync(600);
      const submission = draft.beginSubmission();
      assert(submission);
      if (reason === "submit") resolve(warm);
      const result = submission.take(
        reason === "mismatch" ? { ...options, model: "different" } : options,
      );
      expect(result).toEqual(
        ["failure", "cold fallback"].includes(reason) ? lease : null,
      );
      submission.finish(reason !== "failure");
      await vi.advanceTimersByTimeAsync(0);
      expect(client.cancelTaskRun).toHaveBeenCalledExactlyOnceWith(
        warm.task_id,
        warm.run_id,
        undefined,
        true,
      );
    },
  );

  it("prevents identical composers from sharing ownership while isolating account and project scopes", async () => {
    const { client, draft, service } = setup();
    draft.update(options, client);
    const other = service.draft("account:project", "other-composer");
    other.update(options, client);
    await vi.advanceTimersByTimeAsync(600);
    expect(client.warmTask).toHaveBeenCalledTimes(1);
    expect(other.beginSubmission()?.take(options)).toBeNull();
    expect(draft.beginSubmission()?.take(options)).toEqual(lease);
    service.draft("other-account:project", "composer").update(options, client);
    service.draft("account:other-project", "composer").update(options, client);
    await vi.advanceTimersByTimeAsync(600);
    expect(client.warmTask).toHaveBeenCalledTimes(3);
  });

  it("does not retry throttled speculation and leaves submission available", async () => {
    const { client, draft } = setup();
    client.warmTask.mockRejectedValueOnce(new Error("429"));
    draft.update(options, client);
    await vi.advanceTimersByTimeAsync(600);
    draft.update({ ...options, branch: "feature" }, client);
    await vi.advanceTimersByTimeAsync(600);
    expect(client.warmTask).toHaveBeenCalledTimes(1);
    expect(draft.beginSubmission()?.take(options)).toBeNull();
  });
});
