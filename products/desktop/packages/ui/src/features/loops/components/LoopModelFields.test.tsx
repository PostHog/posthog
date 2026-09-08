import type { LoopSchemas } from "@posthog/api-client/loops";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { LoopModelFields } from "./LoopModelFields";

vi.mock("@posthog/ui/features/sessions/useModelRolloutFlags", () => ({
  useModelRolloutFlags: () => ({
    glm: false,
    glm53: false,
    glm53Flash: false,
    kimi: false,
    deepseek: false,
  }),
}));
vi.mock("../hooks/useLoopModelConfigOptions", () => ({
  useLoopModelConfigOptions: () => [],
}));
// A native select stands in for the dropdown so the test can read the offered
// options and pick one without driving a popup.
vi.mock("@posthog/ui/features/settings/SettingsOptionSelect", () => ({
  SettingsOptionSelect: ({
    value,
    options,
    onValueChange,
    disabled,
    ariaLabel,
  }: {
    value: string;
    options: { value: string; label: string }[];
    onValueChange: (value: string) => void;
    disabled?: boolean;
    ariaLabel: string;
  }) => (
    <select
      aria-label={ariaLabel}
      value={value}
      disabled={disabled}
      onChange={(event) => onValueChange(event.target.value)}
    >
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  ),
}));

function renderFields({
  model = "",
  reasoningEffort = null,
  adapterEditable,
  onReasoningEffortChange = vi.fn(),
}: {
  model?: string;
  reasoningEffort?: LoopSchemas.LoopReasoningEffortEnum | null;
  adapterEditable: boolean;
  onReasoningEffortChange?: (
    effort: LoopSchemas.LoopReasoningEffortEnum | null,
  ) => void;
}) {
  render(
    <LoopModelFields
      adapter="claude"
      model={model}
      reasoningEffort={reasoningEffort}
      adapterEditable={adapterEditable}
      onAdapterChange={vi.fn()}
      onModelChange={vi.fn()}
      onReasoningEffortChange={onReasoningEffortChange}
    />,
  );
}

function effortOptionValues(): string[] {
  const select = screen.getByRole("combobox", { name: "Reasoning effort" });
  return within(select)
    .getAllByRole("option")
    .map((option) => (option as HTMLOptionElement).value);
}

describe("LoopModelFields reasoning effort", () => {
  it.each([
    {
      name: "waits for a pinned model in workflow mode",
      adapterEditable: false,
      model: "",
      expectedDisabled: true,
      expectedValues: ["auto"],
    },
    {
      name: "offers the pinned model's efforts in workflow mode",
      adapterEditable: false,
      model: "claude-sonnet-5",
      expectedDisabled: false,
      expectedValues: [
        "auto",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
        "ultracode",
      ],
    },
    {
      name: "offers the default model's efforts when the adapter is editable",
      adapterEditable: true,
      model: "",
      expectedDisabled: false,
      expectedValues: [
        "auto",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
        "ultracode",
      ],
    },
  ])(
    "$name",
    ({ adapterEditable, model, expectedDisabled, expectedValues }) => {
      renderFields({ adapterEditable, model });

      const select = screen.getByRole("combobox", { name: "Reasoning effort" });
      expect(select).toHaveProperty("disabled", expectedDisabled);
      expect(effortOptionValues()).toEqual(expectedValues);
      expect(
        screen.queryByText("Pick a model to set reasoning effort.") !== null,
      ).toBe(expectedDisabled);
    },
  );

  it("clears the effort when a workflow loop goes back to the default model", async () => {
    const onReasoningEffortChange = vi.fn();
    renderFields({
      adapterEditable: false,
      model: "claude-sonnet-5",
      reasoningEffort: "high",
      onReasoningEffortChange,
    });

    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Model" }),
      "__default__",
    );

    expect(onReasoningEffortChange).toHaveBeenCalledWith(null);
  });
});
