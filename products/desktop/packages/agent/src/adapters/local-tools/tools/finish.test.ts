import { describe, expect, it, vi } from "vitest";
import { enabledLocalTools } from "../index";
import type { LocalToolCtx, LocalToolGateMeta } from "../registry";
import { FINISH_TOOL_NAME, finishSchema, finishTool } from "./finish";

describe("finish tool", () => {
  const requestFinish = async (): Promise<void> => {};

  it.each([
    {
      name: "background cloud run with requestFinish",
      ctx: { cwd: "/repo", requestFinish },
      meta: { environment: "cloud", background: true },
      expected: true,
    },
    {
      name: "background cloud run without requestFinish",
      ctx: { cwd: "/repo" },
      meta: { environment: "cloud", background: true },
      expected: false,
    },
    {
      name: "interactive cloud run (background unset)",
      ctx: { cwd: "/repo", requestFinish },
      meta: { environment: "cloud" },
      expected: false,
    },
    {
      name: "interactive cloud run (background false)",
      ctx: { cwd: "/repo", requestFinish },
      meta: { environment: "cloud", background: false },
      expected: false,
    },
    {
      name: "background local run",
      ctx: { cwd: "/repo", requestFinish },
      meta: { environment: "local", background: true },
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
      { status: "failed", reason: "ran out of quota" },
    );
    expect(spy).toHaveBeenCalledWith("failed", "ran out of quota");
    expect(result.isError).toBeUndefined();
  });

  it("errors when requestFinish is unavailable", async () => {
    const result = await finishTool.handler(
      { cwd: "/repo" },
      { status: "completed" },
    );
    expect(result.isError).toBe(true);
  });
});
