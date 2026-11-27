import { describe, expect, it, vi } from "vitest";

const updateTaskRun = vi.fn();

vi.mock("../signed-commit-artefacts", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../signed-commit-artefacts")>()),
  createSandboxPosthogClient: () => ({ updateTaskRun }),
}));

import { enabledLocalTools } from "../index";
import type { LocalToolCtx, LocalToolGateMeta } from "../registry";
import {
  buildFinishRunUpdate,
  FINISH_REPORT_MAX_CHARS,
  FINISH_TOOL_NAME,
  finishSchema,
  finishTool,
} from "./finish";

describe("finish tool", () => {
  const requestFinish = async (): Promise<void> => {};

  it.each([
    {
      name: "background cloud run that may end itself",
      ctx: { cwd: "/repo", requestFinish },
      meta: { environment: "cloud", background: true, finishTool: true },
      expected: true,
    },
    {
      name: "background cloud run whose launch withholds the tool",
      ctx: { cwd: "/repo", requestFinish },
      meta: { environment: "cloud", background: true, finishTool: false },
      expected: false,
    },
    {
      name: "background cloud run with no launch decision",
      ctx: { cwd: "/repo", requestFinish },
      meta: { environment: "cloud", background: true },
      expected: false,
    },
    {
      name: "background cloud run without requestFinish or run ids",
      ctx: { cwd: "/repo" },
      meta: { environment: "cloud", background: true, finishTool: true },
      expected: false,
    },
    {
      name: "background cloud run with run ids only (out-of-process adapter)",
      ctx: { cwd: "/repo", taskId: "task-1", taskRunId: "run-1" },
      meta: { environment: "cloud", background: true, finishTool: true },
      expected: true,
    },
    {
      name: "withheld run with run ids only (out-of-process adapter)",
      ctx: { cwd: "/repo", taskId: "task-1", taskRunId: "run-1" },
      meta: { environment: "cloud", background: true, finishTool: false },
      expected: false,
    },
    {
      name: "interactive cloud run (background unset)",
      ctx: { cwd: "/repo", requestFinish },
      meta: { environment: "cloud", finishTool: true },
      expected: false,
    },
    {
      name: "interactive cloud run (background false)",
      ctx: { cwd: "/repo", requestFinish },
      meta: { environment: "cloud", background: false, finishTool: true },
      expected: false,
    },
    {
      name: "background local run",
      ctx: { cwd: "/repo", requestFinish },
      meta: { environment: "local", background: true, finishTool: true },
      expected: false,
    },
    {
      name: "no gate meta",
      ctx: { cwd: "/repo", requestFinish },
      meta: undefined,
      expected: false,
    },
  ] as {
    name: string;
    ctx: LocalToolCtx;
    meta: LocalToolGateMeta | undefined;
    expected: boolean;
  }[])("is exposed only for $name → $expected", ({ ctx, meta, expected }) => {
    const tools = enabledLocalTools(ctx, meta);
    expect(tools.some((t) => t.name === FINISH_TOOL_NAME)).toBe(expected);
  });

  it("stays visible without ToolSearch (alwaysLoad)", () => {
    expect(finishTool.alwaysLoad).toBe(true);
  });

  it("defaults status to completed", () => {
    expect(finishSchema.status.parse(undefined)).toBe("completed");
  });

  it("rejects an unknown status", () => {
    expect(finishSchema.status.safeParse("aborted").success).toBe(false);
  });

  it("marks the run terminal via requestFinish", async () => {
    const spy = vi.fn(async () => {});
    const result = await finishTool.handler(
      { cwd: "/repo", requestFinish: spy },
      {
        status: "failed",
        reason: "ran out of quota",
        report: "Partial report",
      },
    );
    expect(spy).toHaveBeenCalledWith(
      "failed",
      "ran out of quota",
      "Partial report",
    );
    expect(result.isError).toBeUndefined();
  });

  it("marks the run terminal via the API when no requestFinish callback exists", async () => {
    updateTaskRun.mockResolvedValue({});
    const result = await finishTool.handler(
      { cwd: "/repo", taskId: "task-1", taskRunId: "run-1" },
      { status: "failed", reason: "blocked" },
    );
    expect(updateTaskRun).toHaveBeenCalledWith(
      "task-1",
      "run-1",
      {
        status: "failed",
        error_message: "blocked",
        error_type: "agent_declined",
      },
      expect.any(AbortSignal),
    );
    expect(result.isError).toBeUndefined();
  });

  it.each(["", "   "])(
    "keeps a report-required run open when the report is %j",
    async (report) => {
      const spy = vi.fn(async () => {});
      const result = await finishTool.handler(
        { cwd: "/repo", requestFinish: spy, finishReportRequired: true },
        { status: "completed", report },
      );
      expect(spy).not.toHaveBeenCalled();
      expect(result.isError).toBe(true);
    },
  );

  const rejectOnce = (status: number) =>
    vi
      .fn<NonNullable<LocalToolCtx["requestFinish"]>>()
      .mockRejectedValueOnce(Object.assign(new Error("rejected"), { status }))
      .mockResolvedValue(undefined);

  it.each([400, 403])(
    "ends the run without the report when the backend rejects it (%i)",
    async (status) => {
      const spy = rejectOnce(status);
      const result = await finishTool.handler(
        { cwd: "/repo", requestFinish: spy },
        { status: "completed", report: "Full report" },
      );
      expect(result.isError).toBeUndefined();
      expect(spy).toHaveBeenLastCalledWith("completed", undefined);
    },
  );

  it("keeps the report when the finish fails for another reason", async () => {
    const spy = rejectOnce(500);
    await expect(
      finishTool.handler(
        { cwd: "/repo", requestFinish: spy },
        { status: "completed", report: "Full report" },
      ),
    ).rejects.toThrow("rejected");
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("cuts a long report without splitting a surrogate pair", () => {
    const report = `${"a".repeat(FINISH_REPORT_MAX_CHARS - 1)}😀😀`;
    const finalMessage = buildFinishRunUpdate("completed", undefined, report)
      .output?.final_message as string;
    expect(finalMessage).toBe(`${"a".repeat(FINISH_REPORT_MAX_CHARS - 1)}😀`);
    expect(finalMessage.isWellFormed()).toBe(true);
  });

  it("errors when requestFinish is unavailable", async () => {
    const result = await finishTool.handler(
      { cwd: "/repo" },
      { status: "completed" },
    );
    expect(result.isError).toBe(true);
  });
});
