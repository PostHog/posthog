import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { useSideQuestionStore } from "../sideQuestionStore";
import { SideQuestionCard } from "./SideQuestionCard";

describe("SideQuestionCard", () => {
  beforeEach(() => {
    useSideQuestionStore.setState({ byTaskId: {} });
  });

  it("renders nothing when there is no entry for the task", () => {
    const { container } = render(
      <Theme>
        <SideQuestionCard taskId="task-1" />
      </Theme>,
    );
    expect(container.firstElementChild).toBeEmptyDOMElement();
  });

  it("shows a spinner while the question is pending", () => {
    useSideQuestionStore.setState({
      byTaskId: {
        "task-1": { id: "q-1", question: "what changed?", status: "pending" },
      },
    });

    render(
      <Theme>
        <SideQuestionCard taskId="task-1" />
      </Theme>,
    );

    expect(screen.getByText("what changed?")).toBeInTheDocument();
    expect(screen.getByText("Answering…")).toBeInTheDocument();
  });

  it("renders the answer once done", () => {
    useSideQuestionStore.setState({
      byTaskId: {
        "task-1": {
          id: "q-1",
          question: "what changed?",
          status: "done",
          answer: "The function parses JSONL.",
        },
      },
    });

    render(
      <Theme>
        <SideQuestionCard taskId="task-1" />
      </Theme>,
    );

    expect(screen.getByText("The function parses JSONL.")).toBeInTheDocument();
  });

  it("renders the error message on failure", () => {
    useSideQuestionStore.setState({
      byTaskId: {
        "task-1": {
          id: "q-1",
          question: "what changed?",
          status: "error",
          error: "Side question timed out",
        },
      },
    });

    render(
      <Theme>
        <SideQuestionCard taskId="task-1" />
      </Theme>,
    );

    expect(screen.getByText("Side question timed out")).toBeInTheDocument();
  });

  it("dismisses the entry when the dismiss button is clicked", () => {
    useSideQuestionStore.setState({
      byTaskId: {
        "task-1": { id: "q-1", question: "what changed?", status: "pending" },
      },
    });

    render(
      <Theme>
        <SideQuestionCard taskId="task-1" />
      </Theme>,
    );

    fireEvent.click(screen.getByLabelText("Dismiss side question"));

    expect(useSideQuestionStore.getState().byTaskId["task-1"]).toBeUndefined();
  });
});
