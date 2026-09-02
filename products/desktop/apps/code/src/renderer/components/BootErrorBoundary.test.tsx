import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const { logError } = vi.hoisted(() => ({ logError: vi.fn() }));

vi.mock("@posthog/ui/shell/logger", () => ({
  logger: {
    scope: () => ({
      error: logError,
      info: vi.fn(),
      warn: vi.fn(),
      debug: vi.fn(),
    }),
  },
}));

import {
  BootErrorBoundary,
  BootErrorScreen,
} from "@components/BootErrorBoundary";

function ThrowOnRender({ message }: { message: string }): never {
  throw new Error(message);
}

describe("BootErrorScreen", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("renders the alert, title and an Error message", () => {
    render(<BootErrorScreen error={new Error("kaboom")} />);

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("PostHog failed to start")).toBeInTheDocument();
    expect(screen.getByText("kaboom")).toBeInTheDocument();
  });

  it("stringifies a non-Error value", () => {
    render(<BootErrorScreen error="plain string failure" />);

    expect(screen.getByText("plain string failure")).toBeInTheDocument();
  });

  it("reloads the window when Reload is clicked", () => {
    const reload = vi.fn();
    vi.stubGlobal("location", { reload });

    render(<BootErrorScreen error={new Error("x")} />);
    fireEvent.click(screen.getByRole("button", { name: /reload/i }));

    expect(reload).toHaveBeenCalledTimes(1);
  });
});

describe("BootErrorBoundary", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders children when no error is thrown", () => {
    render(
      <BootErrorBoundary>
        <span>healthy child</span>
      </BootErrorBoundary>,
    );

    expect(screen.getByText("healthy child")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("catches a render error, shows the fallback and logs it", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});

    render(
      <BootErrorBoundary>
        <ThrowOnRender message="render boom" />
      </BootErrorBoundary>,
    );

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("render boom")).toBeInTheDocument();
    expect(logError).toHaveBeenCalled();
  });

  it("derives error state from a thrown error", () => {
    const error = new Error("derive");
    expect(BootErrorBoundary.getDerivedStateFromError(error)).toEqual({
      error,
    });
  });
});
