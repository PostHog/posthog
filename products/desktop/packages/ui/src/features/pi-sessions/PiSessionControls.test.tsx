import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { PiModelSelector } from "./PiSessionControls";

describe("PiModelSelector", () => {
  it("keeps Pi configuration open while changing the model", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    const onChange = vi.fn();
    const onThinkingLevelChange = vi.fn();
    const onHarnessChange = vi.fn();
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
          onChange={onChange}
          onThinkingLevelChange={onThinkingLevelChange}
          onHarnessChange={onHarnessChange}
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

    const terra = await screen.findByRole("menuitemradio", {
      name: "GPT-5.6 Terra",
    });
    expect(terra).toBeInTheDocument();

    fireEvent.click(terra);

    expect(onChange).toHaveBeenCalledWith({
      provider: "posthog",
      id: "gpt-5.6-terra",
      name: "GPT-5.6 Terra",
    });
    expect(
      screen.getByRole("menuitem", { name: /^Model/ }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("menuitem", { name: /^Reasoning/ }));
    fireEvent.click(await screen.findByRole("menuitemradio", { name: "High" }));

    expect(onThinkingLevelChange).toHaveBeenCalledWith("high");
    expect(
      screen.getByRole("menuitem", { name: /^Reasoning/ }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("menuitem", { name: /^Harness/ }));
    fireEvent.click(
      await screen.findByRole("menuitemradio", { name: "Codex" }),
    );

    expect(onHarnessChange).toHaveBeenCalledWith("codex");
    expect(
      screen.getByRole("menuitem", { name: /^Harness/ }),
    ).toBeInTheDocument();
  });

  it("keeps an open menu mounted while the Pi catalog loads", async () => {
    render(
      <Theme>
        <PiModelSelector
          models={[]}
          isLoading
          onChange={vi.fn()}
          onHarnessChange={vi.fn()}
          menuOpen
          onMenuOpenChange={vi.fn()}
        />
      </Theme>,
    );

    expect(screen.getByRole("button", { name: /Loading/ })).toBeInTheDocument();
    expect(
      await screen.findByRole("menuitem", { name: /^Harness/ }),
    ).toBeInTheDocument();
  });
});
