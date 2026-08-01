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
      heading: "Starting Pi…",
      subtitle: "Connecting to Pi on this device.",
    },
    {
      executionTarget: "cloud" as const,
      heading: "Getting things ready…",
      subtitle: "Connecting to your cloud runner.",
    },
    {
      executionTarget: "cloud" as const,
      cloudStatus: "in_progress" as const,
      heading: "Starting the sandbox…",
      subtitle: "Connecting to your cloud runner.",
    },
  ])(
    "shows $executionTarget connection copy",
    ({ executionTarget, cloudStatus, heading, subtitle }) => {
      vi.useFakeTimers();

      render(
        <Theme>
          <SessionInitializingView
            executionTarget={executionTarget}
            cloudStatus={cloudStatus}
          />
        </Theme>,
      );

      act(() => {
        vi.advanceTimersByTime(2000);
      });

      expect(screen.getByText(heading)).toBeInTheDocument();
      expect(screen.getByText(subtitle)).toBeInTheDocument();
    },
  );
});
