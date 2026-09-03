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

const privateChannel: SlackChannelOption = {
  ...generalChannel,
  id: "G_PRIVATE",
  name: "private-team",
  is_private: true,
};

vi.mock("@posthog/ui/features/inbox/hooks/useSlackChannels", () => ({
  useSlackChannels: (
    _integrationId: number,
    options?: { search?: string },
  ) => ({
    data: {
      channels: options?.search
        ? [analyticsChannel]
        : [generalChannel, privateChannel],
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
  it("hides private channels only when public channels are required", async () => {
    const user = userEvent.setup();
    const picker = render(
      <SlackChannelCombobox
        integrationId={123}
        value={null}
        onChange={vi.fn()}
        ariaLabel="Slack channel"
      />,
    );

    const trigger = screen.getByRole("combobox", { name: "Slack channel" });
    trigger.focus();
    await user.keyboard("{ArrowDown}");
    expect(screen.getByText("private-team")).toBeInTheDocument();
    picker.unmount();

    render(
      <SlackChannelCombobox
        integrationId={123}
        value={null}
        onChange={vi.fn()}
        ariaLabel="Slack channel"
        publicOnly
      />,
    );

    const publicOnlyTrigger = screen.getByRole("combobox", {
      name: "Slack channel",
    });
    publicOnlyTrigger.focus();
    await user.keyboard("{ArrowDown}");

    expect(screen.getByText("general")).toBeInTheDocument();
    expect(screen.queryByText("private-team")).not.toBeInTheDocument();
  });

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
