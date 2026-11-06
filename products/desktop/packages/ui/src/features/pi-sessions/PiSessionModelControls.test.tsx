import type { PiControllerSessionState } from "@posthog/core/pi-runtime/piSessionStore";
import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PiSessionModelControls } from "./PiSessionModelControls";

const setConfig = vi.hoisted(() => vi.fn());
const catalog = vi.hoisted(() => ({ models: [] as unknown[] }));

const CATALOG_MODELS = [
  {
    provider: "posthog",
    id: "claude-opus-5",
    name: "Claude Opus 5",
    contextWindow: 1_000_000,
    thinkingLevels: ["off", "high"],
  },
];

vi.mock("./piPendingConfigStore", () => ({
  getPiPendingConfig: () => undefined,
  usePiPendingConfigStore: (
    selector: (state: { setConfig: typeof setConfig }) => unknown,
  ) => selector({ setConfig }),
}));

vi.mock("./usePiModelCatalog", () => ({
  usePiModelCatalog: () => ({ data: catalog.models, isPending: false }),
}));

function piSession(
  models: Array<{ provider: string; id: string }>,
  currentModelId: string,
): PiControllerSessionState {
  return {
    connectionState: "connected",
    events: [],
    models,
    modelsLoaded: true,
    thinkingLevels: ["off", "high"],
    thinkingLevelsLoaded: true,
    commands: [],
    status: {
      model: { provider: "posthog", id: currentModelId },
      thinkingLevel: "high",
    },
    queue: { steering: [], followUp: [] },
    authRestoring: false,
    isBashRunning: false,
  } as unknown as PiControllerSessionState;
}

async function openModelMenu(currentModelId: string): Promise<void> {
  const user = userEvent.setup({ pointerEventsCheck: 0 });
  await user.click(
    screen.getByRole("button", {
      name: `Model and reasoning: ${currentModelId} High`,
    }),
  );
  await user.click(await screen.findByRole("menuitem", { name: /^Model/ }));
}

describe("PiSessionModelControls", () => {
  beforeEach(() => {
    catalog.models = CATALOG_MODELS;
  });

  it("uses the catalog instead of the unfiltered local runtime models", async () => {
    render(
      <Theme>
        <PiSessionModelControls
          taskId="task-1"
          session={piSession(
            [
              { provider: "posthog", id: "claude-opus-4-8" },
              { provider: "posthog", id: "claude-opus-5" },
            ],
            "claude-opus-4-8",
          )}
          controller={{} as never}
          isOnline
          onError={vi.fn()}
        />
      </Theme>,
    );

    await openModelMenu("claude-opus-4-8");

    expect(
      await screen.findByRole("menuitemradio", { name: "Claude Opus 5" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("menuitemradio", { name: "claude-opus-4-8" }),
    ).not.toBeInTheDocument();
  });

  it("hides retired models from the runtime list when the catalog is empty", async () => {
    catalog.models = [];

    render(
      <Theme>
        <PiSessionModelControls
          taskId="task-1"
          session={piSession(
            [
              { provider: "posthog", id: "gpt-5.4" },
              { provider: "posthog", id: "gpt-5.6-sol" },
            ],
            "gpt-5.6-sol",
          )}
          controller={{} as never}
          isOnline
          onError={vi.fn()}
        />
      </Theme>,
    );

    await openModelMenu("gpt-5.6-sol");

    expect(
      await screen.findByRole("menuitemradio", { name: /gpt-5\.6-sol/ }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("menuitemradio", { name: /gpt-5\.4/ }),
    ).not.toBeInTheDocument();
  });
});
