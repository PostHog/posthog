import type {
  SessionConfigOption,
  SessionConfigSelectGroup,
} from "@agentclientprotocol/sdk";
import { Theme } from "@radix-ui/themes";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { UnifiedModelSelector } from "./UnifiedModelSelector";

const groupedCodexModel: SessionConfigOption = {
  type: "select",
  id: "model",
  name: "Model",
  category: "model",
  currentValue: "gpt-5.5",
  options: [
    {
      group: "openai",
      name: "OpenAI",
      options: [
        { value: "gpt-5.5", name: "GPT-5.5" },
        { value: "gpt-5.5-codex", name: "GPT-5.5 Codex" },
      ],
    },
    {
      group: "fable",
      name: "Fable",
      options: [{ value: "fable", name: "Fable" }],
    },
  ] satisfies SessionConfigSelectGroup[],
};

const flatCodexModel: SessionConfigOption = {
  type: "select",
  id: "model",
  name: "Model",
  category: "model",
  currentValue: "gpt-5.5",
  options: [
    { value: "gpt-5.5", name: "GPT-5.5" },
    { value: "fable", name: "Fable" },
  ],
};

function renderSelector(
  props: Partial<React.ComponentProps<typeof UnifiedModelSelector>> = {},
) {
  return render(
    <Theme>
      <UnifiedModelSelector
        modelOption={groupedCodexModel}
        adapter="codex"
        onAdapterChange={vi.fn()}
        onModelChange={vi.fn()}
        {...props}
      />
    </Theme>,
  );
}

describe("UnifiedModelSelector", () => {
  it("renders the codex adapter label, group labels, and grouped model items", async () => {
    const user = userEvent.setup();
    renderSelector();

    await user.click(screen.getByRole("button", { name: "Model" }));

    // Every model in every group renders as a radio item.
    expect(
      await screen.findByRole("menuitemradio", { name: "GPT-5.5" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("menuitemradio", { name: "GPT-5.5 Codex" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("menuitemradio", { name: "Fable" }),
    ).toBeInTheDocument();
    // Adapter MenuLabel + group MenuLabels render.
    expect(screen.getByText("Codex")).toBeInTheDocument();
    expect(screen.getByText("OpenAI")).toBeInTheDocument();
  });

  it("renders flat (ungrouped) model items", async () => {
    const user = userEvent.setup();
    renderSelector({ modelOption: flatCodexModel });

    await user.click(screen.getByRole("button", { name: "Model" }));

    expect(
      await screen.findByRole("menuitemradio", { name: "GPT-5.5" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("menuitemradio", { name: "Fable" }),
    ).toBeInTheDocument();
  });

  it("fires onModelChange exactly once with the picked value after the menu closes", async () => {
    const user = userEvent.setup();
    const onModelChange = vi.fn();
    renderSelector({ onModelChange });

    await user.click(screen.getByRole("button", { name: "Model" }));
    await user.click(
      await screen.findByRole("menuitemradio", { name: "GPT-5.5 Codex" }),
    );

    // onModelChange is deferred until the menu-close animation completes, so
    // wait for it rather than asserting synchronously after the click.
    await waitFor(() =>
      expect(onModelChange).toHaveBeenCalledExactlyOnceWith("gpt-5.5-codex"),
    );
  });

  it("switches adapter via the 'Switch to Claude' item", async () => {
    const user = userEvent.setup();
    const onAdapterChange = vi.fn();
    renderSelector({ onAdapterChange });

    await user.click(screen.getByRole("button", { name: "Model" }));
    await user.click(
      await screen.findByRole("menuitem", { name: /switch to claude/i }),
    );

    expect(onAdapterChange).toHaveBeenCalledExactlyOnceWith("claude");
  });

  it("renders a disabled loading button with no menu while connecting", () => {
    renderSelector({ isConnecting: true });

    const button = screen.getByRole("button", { name: /loading/i });
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(
      screen.queryByRole("button", { name: "Model" }),
    ).not.toBeInTheDocument();
  });
});
