import type { SlackChannelOption } from "@posthog/shared/domain-types";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { SlackChannelCombobox } from "./SlackChannelCombobox";

const generalChannel: SlackChannelOption = {
  id: "C_GENERAL",
  name: "general",
  is_private: false,
  is_member: true,
  is_ext_shared: false,
  is_private_without_access: false,
};

const analyticsChannel: SlackChannelOption = {
  ...generalChannel,
  id: "C_ANALYTICS",
  name: "analytics-platform",
};

vi.mock("@posthog/ui/features/inbox/hooks/useSlackChannels", () => ({
  useSlackChannels: (
    _integrationId: number,
    options?: { search?: string },
  ) => ({
    data: {
      channels: options?.search ? [analyticsChannel] : [generalChannel],
    },
    isFetching: false,
  }),
}));

vi.mock("@posthog/ui/primitives/hooks/useDebouncedValue", () => ({
  useDebouncedValue: <T,>(value: T) => ({
    debounced: value,
    isPending: false,
  }),
}));

describe("SlackChannelCombobox", () => {
  it("updates server search results without replacing the focused input", async () => {
    const user = userEvent.setup();

    function TestPicker() {
      const [value, setValue] = useState<string | null>(null);
      return (
        <SlackChannelCombobox
          integrationId={123}
          value={value}
          onChange={setValue}
          ariaLabel="Slack channel"
        />
      );
    }

    render(<TestPicker />);

    const trigger = screen.getByRole("combobox", { name: "Slack channel" });
    trigger.focus();
    await user.keyboard("{ArrowDown}");
    expect(screen.getByText("general")).toBeInTheDocument();
    expect(screen.queryByText("No channel selected")).not.toBeInTheDocument();

    const input = screen.getByPlaceholderText("Search channels…");
    await user.type(input, "analytics");

    expect(input).toHaveFocus();
    expect(screen.getByText("analytics-platform")).toBeInTheDocument();
    expect(screen.queryByText("general")).not.toBeInTheDocument();
  });
});
