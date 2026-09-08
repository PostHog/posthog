import { Theme } from "@radix-ui/themes";
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
      subtitle: "Connecting to Pi on this device.",
    },
    {
      executionTarget: "cloud" as const,
      subtitle: "Connecting to your cloud runner.",
    },
  ])(
    "shows Loading through $executionTarget startup",
    ({ executionTarget, subtitle }) => {
      vi.useFakeTimers();

      render(
        <Theme>
          <SessionInitializingView executionTarget={executionTarget} />
        </Theme>,
      );

      expect(screen.getByText("Loading")).toBeInTheDocument();

      act(() => {
        vi.advanceTimersByTime(2000);
      });

      expect(screen.getByText("Loading")).toBeInTheDocument();
      expect(screen.getByText(subtitle)).toBeInTheDocument();
    },
  );
});
