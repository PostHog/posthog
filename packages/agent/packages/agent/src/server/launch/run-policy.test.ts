import { describe, expect, it } from "vitest";
import { type RunPolicy, runPolicyFromOrigin } from "./run-policy";

interface Case {
  name: string;
  originProduct: string | null;
  endRunWhenDone?: boolean;
  callerEndsRun?: boolean;
  expected: Partial<RunPolicy>;
}

describe("runPolicyFromOrigin", () => {
  it.each<Case>([
    {
      name: "a run that ends itself",
      originProduct: "user_created",
      expected: { finishTool: true, finishReportRequired: false },
    },
    {
      name: "an unknown origin",
      originProduct: null,
      expected: { finishTool: false },
    },
    {
      name: "an empty origin",
      originProduct: "",
      expected: { finishTool: false },
    },
    {
      name: "an unknown origin with the end-run opt-in",
      originProduct: null,
      endRunWhenDone: true,
      expected: { finishTool: true, finishReportRequired: false },
    },
    {
      name: "a caller-managed assessment run",
      originProduct: "signal_report",
      callerEndsRun: true,
      expected: { finishTool: false },
    },
    {
      name: "a workflow run",
      originProduct: "workflow",
      expected: { finishTool: false, finishReportRequired: false },
    },
    {
      name: "a workflow run with the end-run opt-in",
      originProduct: "workflow",
      endRunWhenDone: true,
      expected: { finishTool: true, finishReportRequired: true },
    },
    {
      name: "a non-workflow run with the end-run opt-in",
      originProduct: "user_created",
      endRunWhenDone: true,
      expected: { finishTool: true, finishReportRequired: false },
    },
    {
      name: "a ReviewHog run",
      originProduct: "review_hog",
      expected: { finishTool: false },
    },
    {
      name: "a ReviewHog run with the end-run opt-in",
      originProduct: "review_hog",
      endRunWhenDone: true,
      expected: { finishTool: false },
    },
    {
      name: "a scout suggestions run",
      originProduct: "scout_suggestions",
      expected: { finishTool: false },
    },
    {
      name: "a scout suggestions run with the end-run opt-in",
      originProduct: "scout_suggestions",
      endRunWhenDone: true,
      expected: { finishTool: false },
    },
    {
      name: "a task analysis run",
      originProduct: "task_analysis",
      expected: { reportActivityTool: true },
    },
    {
      name: "a run that reports no activity",
      originProduct: "user_created",
      expected: { reportActivityTool: false },
    },
  ])(
    "resolves $name",
    ({
      originProduct,
      endRunWhenDone = false,
      callerEndsRun = false,
      expected,
    }) => {
      expect(
        runPolicyFromOrigin({ originProduct, endRunWhenDone, callerEndsRun }),
      ).toMatchObject(expected);
    },
  );
});
