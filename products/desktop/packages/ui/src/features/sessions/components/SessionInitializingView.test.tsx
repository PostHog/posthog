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
      title: "Starting local agent",
    },
    {
      executionTarget: "cloud" as const,
      title: "Starting cloud agent",
    },
  ])(
    "shows the current step through $executionTarget startup",
    ({ executionTarget, title }) => {
      vi.useFakeTimers();

      render(<SessionInitializingView executionTarget={executionTarget} />);

      expect(screen.getByRole("status").textContent).toBe(title);

      act(() => {
        vi.advanceTimersByTime(2000);
      });

      expect(screen.getByRole("status").textContent).toBe(title);
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
    expect(screen.getByRole("status").textContent).toBe(
      "Running repository setup",
    );
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
