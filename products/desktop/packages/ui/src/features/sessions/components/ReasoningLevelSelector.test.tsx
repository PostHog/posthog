import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import { Theme } from "@radix-ui/themes";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ReasoningLevelSelector } from "./ReasoningLevelSelector";

function codexThoughtOption(
  overrides?: Partial<SessionConfigOption>,
): SessionConfigOption {
  return {
    type: "select",
    id: "effort",
    name: "Reasoning effort",
    category: "thought_level",
    currentValue: "high",
    options: [
      { name: "low", value: "low" },
      { name: "high", value: "high" },
      { name: "max", value: "max" },
    ],
    ...overrides,
  } as unknown as SessionConfigOption;
}

describe("ReasoningLevelSelector", () => {
  it("renders the active level as the trigger label for a codex thought_level option", () => {
    render(
      <Theme>
        <ReasoningLevelSelector
          thoughtOption={codexThoughtOption()}
          adapter="codex"
        />
      </Theme>,
    );
    expect(
      screen.getByRole("button", { name: "Reasoning: high" }),
    ).toBeInTheDocument();
  });

  it("emits the raw value via onChange once the menu closes", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <Theme>
        <ReasoningLevelSelector
          thoughtOption={codexThoughtOption()}
          adapter="codex"
          onChange={onChange}
        />
      </Theme>,
    );

    await user.click(screen.getByRole("button", { name: "Reasoning: high" }));
    const lowItem = await screen.findByRole("menuitemradio", { name: "low" });
    await user.click(lowItem);

    await waitFor(() => expect(onChange).toHaveBeenCalledWith("low"));
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("uses the 'Effort' label for the claude adapter", () => {
    render(
      <Theme>
        <ReasoningLevelSelector
          thoughtOption={codexThoughtOption({ currentValue: "medium" })}
          adapter="claude"
        />
      </Theme>,
    );
    expect(
      screen.getByRole("button", { name: "Effort: medium" }),
    ).toBeInTheDocument();
  });

  it.each([
    ["undefined option", undefined],
    ["non-select type", codexThoughtOption({ type: "boolean" })],
    ["empty options", codexThoughtOption({ options: [] })],
  ])("renders no trigger for %s", (_label, option) => {
    render(
      <ReasoningLevelSelector
        thoughtOption={option as SessionConfigOption | undefined}
        adapter="codex"
      />,
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
