import type { AutoresearchRun } from "@posthog/core/autoresearch/schemas";
import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PreBaselineState } from "./PreBaselineState";

function makeRun(overrides: Partial<AutoresearchRun> = {}): AutoresearchRun {
  return {
    id: "run-1",
    config: {
      taskId: "task-1",
      direction: "minimize",
      targetValue: null,
      maxIterations: 10,
      implementModel: null,
      measureModel: null,
      implementEffort: null,
      measureEffort: null,
      instructions: "Reduce memory usage.",
    },
    status: "running",
    metricName: null,
    metricUnit: null,
    phase: null,
    originalModel: null,
    originalEffort: null,
    researchFindings: [],
    iterations: [],
    startedAt: 0,
    endedAt: null,
    endReason: null,
    interruptedReason: null,
    lastError: null,
    ...overrides,
  };
}

function renderState(
  run: AutoresearchRun,
  sessionActivity: React.ComponentProps<
    typeof PreBaselineState
  >["sessionActivity"],
) {
  return render(
    <Theme>
      <PreBaselineState run={run} sessionActivity={sessionActivity} />
    </Theme>,
  );
}

describe("PreBaselineState", () => {
  it("shows active baseline progress and loading dashboard placeholders", () => {
    renderState(makeRun(), {
      status: "connected",
      isPromptPending: true,
      isCompacting: false,
    });

    expect(screen.getByText("Establishing the baseline")).toBeVisible();
    expect(screen.getByRole("status", { name: "Loading" })).toHaveClass(
      "motion-safe:animate-spin",
      "motion-reduce:animate-none",
    );
    const metrics = screen.getByRole("status", {
      name: "Loading autoresearch metrics",
    });
    expect(metrics).toBeVisible();
    expect(
      screen.getByRole("region", { name: "Autoresearch metric summary" }),
    ).toHaveClass(
      "grid-cols-1",
      "@min-[360px]:grid-cols-2",
      "@min-[700px]:grid-cols-4",
    );
    expect(screen.getByText("0 / 10")).toBeVisible();
  });

  it("surfaces codebase research while the baseline is pending", () => {
    renderState(
      makeRun({
        researchFindings: [
          {
            index: 1,
            summary: "Mapped the execution path",
            finding: "The metric is computed in the workspace server.",
            nextStep: "Trace the benchmark command",
            area: "workspace server",
            at: 1,
          },
        ],
      }),
      {
        status: "connected",
        isPromptPending: true,
        isCompacting: false,
      },
    );

    expect(screen.getByText("Researching the codebase")).toBeVisible();
    expect(screen.getByText("Codebase research")).toBeVisible();
    expect(screen.getByText("Mapped the execution path")).toBeVisible();
    expect(
      screen.getByText("The metric is computed in the workspace server."),
    ).toBeVisible();
    expect(screen.getByText("Next: Trace the benchmark command")).toBeVisible();
    const metrics = screen.getByRole("status", {
      name: "Loading autoresearch metrics",
    });
    const research = screen.getByText("Codebase research");
    expect(
      metrics.compareDocumentPosition(research) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("explains when baseline collection is paused", () => {
    renderState(makeRun({ status: "paused" }), null);

    expect(screen.getByText("Baseline measurement paused")).toBeVisible();
    expect(
      screen.getByRole("region", { name: "Autoresearch metric summary" }),
    ).toBeVisible();
    expect(screen.getByText("0 / 10")).toBeVisible();
    expect(
      screen.queryByRole("status", { name: "Loading autoresearch metrics" }),
    ).not.toBeInTheDocument();
  });

  it("does not imply loading after a run ends without a report", () => {
    renderState(
      makeRun({
        status: "failed",
        endReason: "missing-report",
        endedAt: 1,
        lastError: "The agent did not report a metric.",
      }),
      null,
    );

    expect(
      screen.getByText("Run ended before the baseline was reported"),
    ).toBeVisible();
    expect(
      screen.getByText("No metric report was recorded for this run."),
    ).toBeVisible();
  });
});
