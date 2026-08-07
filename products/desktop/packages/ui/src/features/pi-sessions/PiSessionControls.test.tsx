import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { PiModelSelector } from "./PiSessionControls";

describe("PiModelSelector", () => {
  it("keeps Pi configuration in the same nested menu shape as ACP", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    render(
      <Theme>
        <PiModelSelector
          models={[
            {
              provider: "posthog",
              id: "gpt-5.6-sol",
              name: "GPT-5.6 Sol",
            },
            {
              provider: "posthog",
              id: "gpt-5.6-terra",
              name: "GPT-5.6 Terra",
            },
          ]}
          currentModel={{
            provider: "posthog",
            id: "gpt-5.6-sol",
            name: "GPT-5.6 Sol",
          }}
          thinkingLevel="medium"
          thinkingLevels={["low", "medium", "high"]}
          onChange={vi.fn()}
          onThinkingLevelChange={vi.fn()}
          onHarnessChange={vi.fn()}
        />
      </Theme>,
    );

    await user.click(
      screen.getByRole("button", {
        name: "Model and reasoning: GPT-5.6 Sol Medium",
      }),
    );

    expect(
      await screen.findByRole("menuitem", { name: /^Harness Pi/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("menuitem", { name: /^Model/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("menuitem", { name: /^Reasoning/ }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("menuitemradio", { name: "GPT-5.6 Terra" }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("menuitem", { name: /^Model/ }));

    expect(
      await screen.findByRole("menuitemradio", { name: "GPT-5.6 Terra" }),
    ).toBeInTheDocument();
  });
});
