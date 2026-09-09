import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SessionInitializingView } from "./SessionInitializingView";

afterEach(() => {
  vi.useRealTimers();
});

describe("SessionInitializingView", () => {
  it.each([
    {
      executionTarget: "local" as const,
      subtitle: "Connecting to the agent on this device.",
      title: "Starting local agent",
    },
    {
      executionTarget: "cloud" as const,
      subtitle: "Connecting to your cloud runner.",
      title: "Starting cloud agent",
    },
  ])(
    "shows the current step through $executionTarget startup",
    ({ executionTarget, subtitle, title }) => {
      vi.useFakeTimers();

      render(<SessionInitializingView executionTarget={executionTarget} />);

      expect(screen.getByText(title)).toBeInTheDocument();

      act(() => {
        vi.advanceTimersByTime(2000);
      });

      expect(screen.getByText(title)).toBeInTheDocument();
      expect(screen.getByText(subtitle)).toBeInTheDocument();
    },
  );

  it("updates the visible phase when hooks start and finish", () => {
    vi.useFakeTimers();
    const { rerender } = render(
      <SessionInitializingView executionTarget="local" />,
    );
    rerender(
      <SessionInitializingView executionTarget="local" phase="setup_hooks" />,
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "Running repository setup",
    );
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(
      screen.getByText(/A new worktree can take longer/),
    ).toBeInTheDocument();
    rerender(
      <SessionInitializingView
        executionTarget="local"
        phase="sdk_initialization"
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "Starting local agent",
    );
    expect(
      screen.queryByText("Running repository setup"),
    ).not.toBeInTheDocument();
  });
});
