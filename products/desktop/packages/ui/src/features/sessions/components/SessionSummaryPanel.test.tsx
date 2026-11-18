import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useSideQuestionStore } from "../sideQuestionStore";
import { SessionSummaryPanel } from "./SessionSummaryPanel";

vi.mock("@posthog/di/react", () => ({
  useService: () => ({ askSideQuestion: vi.fn() }),
}));
vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));

describe("SessionSummaryPanel", () => {
  beforeEach(() => {
    useSideQuestionStore.setState({ byTaskId: {} });
  });

  const seed = (
    entry: Partial<{ status: string; answer: string; taskRunId: string }>,
  ): void => {
    useSideQuestionStore.setState({
      byTaskId: {
        "task-1": {
          id: "s-1",
          question: "write a handoff",
          taskRunId: "run-1",
          kind: "summary",
          label: "Session summary",
          status: "pending",
          ...entry,
        } as never,
      },
    });
  };

  it("says how long the summary takes and offers a way out while it runs", () => {
    seed({});

    render(
      <Theme>
        <SessionSummaryPanel taskId="task-1" taskRunId="run-1" />
      </Theme>,
    );

    expect(screen.getByText("Session summary")).toBeInTheDocument();
    expect(screen.getByText(/Writing the summary/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Stop waiting"));
    expect(useSideQuestionStore.getState().byTaskId["task-1"]).toBeUndefined();
  });

  it("offers copy and dismiss once the summary is written", () => {
    seed({ status: "done", answer: "The goal is to ship the parser." });

    render(
      <Theme>
        <SessionSummaryPanel taskId="task-1" taskRunId="run-1" />
      </Theme>,
    );

    expect(
      screen.getByText("The goal is to ship the parser."),
    ).toBeInTheDocument();
    expect(screen.getByText("Copy")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Dismiss"));
    expect(useSideQuestionStore.getState().byTaskId["task-1"]).toBeUndefined();
  });

  it("hides a summary written for a prior run", () => {
    seed({ status: "done", answer: "The goal is to ship the parser." });

    const { container } = render(
      <Theme>
        <SessionSummaryPanel taskId="task-1" taskRunId="run-2" />
      </Theme>,
    );

    expect(container.firstElementChild).toBeEmptyDOMElement();
  });
});
