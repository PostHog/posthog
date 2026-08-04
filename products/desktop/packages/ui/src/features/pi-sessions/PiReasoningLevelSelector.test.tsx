import type {
  PiModelSelection,
  PiThinkingLevel,
} from "@posthog/core/pi-runtime/piSessionController";
import { configure, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { PiReasoningLevelSelector } from "./PiReasoningLevelSelector";

// Menu open/close and submenu reveals ride animations that starve under
// parallel suite load; the default 1s async timeout flakes.
configure({ asyncUtilTimeout: 5000 });

vi.mock("@posthog/ui/utils/browser", () => ({ openUrlInBrowser: vi.fn() }));
vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: () => false,
}));

const haiku: PiModelSelection = { provider: "posthog", id: "claude-haiku-4-5" };
const sonnet: PiModelSelection = { provider: "posthog", id: "claude-sonnet-5" };
const thinkingLevels: PiThinkingLevel[] = ["off", "low", "medium", "high"];

function renderSelector(
  overrides?: Partial<Parameters<typeof PiReasoningLevelSelector>[0]>,
) {
  const onModelChange = vi.fn();
  const onThinkingLevelChange = vi.fn();
  render(
    <PiReasoningLevelSelector
      models={[haiku, sonnet]}
      currentModel={haiku}
      thinkingLevels={thinkingLevels}
      currentThinkingLevel="high"
      onModelChange={onModelChange}
      onThinkingLevelChange={onThinkingLevelChange}
      {...overrides}
    />,
  );
  return { onModelChange, onThinkingLevelChange };
}

// Plain polling instead of RTL waitFor: menu transitions complete on timers
// that the act-wrapped waitFor starves under suite load.
async function pollUntil(check: () => boolean, timeoutMs = 5000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (check()) return;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error("condition not met within timeout");
}

async function openSub(user: ReturnType<typeof userEvent.setup>, name: RegExp) {
  const trigger = await screen.findByRole("menuitem", { name });
  await user.click(trigger);
  for (let attempt = 0; attempt < 100; attempt++) {
    if (screen.queryAllByRole("menuitemradio").length > 0) return;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error("submenu did not open");
}

describe("PiReasoningLevelSelector", () => {
  it.each([
    {
      case: "model with thinking",
      overrides: {},
      pill: "Model and reasoning: claude-haiku-4-5 High",
    },
    {
      case: "model without thinking support",
      overrides: { thinkingLevels: ["off"] as PiThinkingLevel[] },
      pill: "Model: claude-haiku-4-5",
    },
    {
      case: "current model missing from the catalog",
      overrides: {
        currentModel: {
          provider: "posthog",
          id: "claude-legacy",
        } as PiModelSelection,
      },
      pill: "Model and reasoning: claude-legacy High",
    },
  ])("renders one unified pill for a $case", ({ overrides, pill }) => {
    renderSelector(overrides);
    expect(screen.getByRole("button", { name: pill })).toBeInTheDocument();
  });

  it("maps a model pick back to the Pi model selection", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    const { onModelChange } = renderSelector();

    await user.click(
      screen.getByRole("button", {
        name: "Model and reasoning: claude-haiku-4-5 High",
      }),
    );
    await user.click(await screen.findByRole("button", { name: "Advanced" }));
    await openSub(user, /^Model/);
    fireEvent.click(
      await screen.findByRole("menuitemradio", { name: "claude-sonnet-5" }),
    );

    await pollUntil(() => onModelChange.mock.calls.length > 0);
    expect(onModelChange).toHaveBeenCalledWith(sonnet);
    expect(onModelChange).toHaveBeenCalledTimes(1);
  });

  it("resets to the default thinking level", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    const { onThinkingLevelChange } = renderSelector({
      currentThinkingLevel: "low",
    });

    await user.click(
      screen.getByRole("button", {
        name: "Model and reasoning: claude-haiku-4-5 Low",
      }),
    );
    await user.click(await screen.findByRole("button", { name: "Advanced" }));
    fireEvent.click(
      await screen.findByRole("menuitem", { name: "Reset to default" }),
    );

    await pollUntil(() => onThinkingLevelChange.mock.calls.length > 0);
    expect(onThinkingLevelChange).toHaveBeenCalledWith("high");
  });

  it("maps a reasoning pick to a Pi thinking level", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    const { onThinkingLevelChange } = renderSelector();

    await user.click(
      screen.getByRole("button", {
        name: "Model and reasoning: claude-haiku-4-5 High",
      }),
    );
    await user.click(await screen.findByRole("button", { name: "Advanced" }));
    await openSub(user, /^Reasoning/);
    fireEvent.click(await screen.findByRole("menuitemradio", { name: "Low" }));

    await pollUntil(() => onThinkingLevelChange.mock.calls.length > 0);
    expect(onThinkingLevelChange).toHaveBeenCalledWith("low");
    expect(onThinkingLevelChange).toHaveBeenCalledTimes(1);
  });

  it("switches harness away from Pi through the advanced view", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    const onHarnessChange = vi.fn();
    renderSelector({ onHarnessChange });

    await user.click(
      screen.getByRole("button", {
        name: "Model and reasoning: claude-haiku-4-5 High",
      }),
    );
    await user.click(await screen.findByRole("button", { name: "Advanced" }));
    await openSub(user, /^Harness Pi/);
    fireEvent.click(
      await screen.findByRole("menuitemradio", { name: "Claude Code" }),
    );

    await pollUntil(() => onHarnessChange.mock.calls.length > 0);
    expect(onHarnessChange).toHaveBeenCalledWith("claude");
    expect(onHarnessChange).toHaveBeenCalledTimes(1);
  });
});
