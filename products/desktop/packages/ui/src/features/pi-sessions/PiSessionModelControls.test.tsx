import type { PiControllerSessionState } from "@posthog/core/pi-runtime/piSessionStore";
import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { PiSessionModelControls } from "./PiSessionModelControls";

const setConfig = vi.hoisted(() => vi.fn());

vi.mock("./piPendingConfigStore", () => ({
  getPiPendingConfig: () => undefined,
  usePiPendingConfigStore: (
    selector: (state: { setConfig: typeof setConfig }) => unknown,
  ) => selector({ setConfig }),
}));

vi.mock("./usePiModelCatalog", () => ({
  usePiModelCatalog: () => ({
    data: [
      {
        provider: "posthog",
        id: "claude-opus-5",
        name: "Claude Opus 5",
        contextWindow: 1_000_000,
        thinkingLevels: ["off", "high"],
      },
    ],
    isPending: false,
  }),
}));

describe("PiSessionModelControls", () => {
  it("uses the catalog instead of the unfiltered local runtime models", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    const session = {
      connectionState: "connected",
      events: [],
      models: [
        { provider: "posthog", id: "claude-opus-4-8" },
        { provider: "posthog", id: "claude-opus-5" },
      ],
      modelsLoaded: true,
      thinkingLevels: ["off", "high"],
      thinkingLevelsLoaded: true,
      commands: [],
      status: {
        model: { provider: "posthog", id: "claude-opus-4-8" },
        thinkingLevel: "high",
      },
      queue: { steering: [], followUp: [] },
      authRestoring: false,
      isBashRunning: false,
    } as unknown as PiControllerSessionState;

    render(
      <Theme>
        <PiSessionModelControls
          taskId="task-1"
          session={session}
          controller={{} as never}
          isOnline
          onError={vi.fn()}
        />
      </Theme>,
    );

    await user.click(
      screen.getByRole("button", {
        name: "Model and reasoning: claude-opus-4-8 High",
      }),
    );
    await user.click(await screen.findByRole("menuitem", { name: /^Model/ }));

    expect(
      await screen.findByRole("menuitemradio", { name: "Claude Opus 5" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("menuitemradio", { name: "claude-opus-4-8" }),
    ).not.toBeInTheDocument();
  });
});
