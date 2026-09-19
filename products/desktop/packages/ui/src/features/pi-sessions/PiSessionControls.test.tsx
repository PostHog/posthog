import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import {
  configure,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { PiModelSelector } from "./PiSessionControls";

// Menu open/close and submenu reveals ride animations that starve under
// parallel suite load; the default 1s async timeout flakes.
configure({ asyncUtilTimeout: 5000 });

const piModels = [
  { provider: "posthog" as const, id: "claude-opus-5", name: "Claude Opus 5" },
  { provider: "posthog" as const, id: "gpt-5.6-terra", name: "GPT-5.6 Terra" },
];

function groupedModelOption(): SessionConfigOption {
  return {
    type: "select",
    id: "model",
    name: "Model",
    category: "model",
    currentValue: "claude-opus-5",
    options: [
      {
        group: "anthropic",
        name: "Anthropic",
        options: [
          {
            name: "Claude Opus 5",
            value: "claude-opus-5",
            _meta: { "posthog.code/modelHarness": "claude" },
          },
        ],
      },
      {
        group: "openai",
        name: "OpenAI",
        options: [
          {
            name: "GPT-5.5",
            value: "gpt-5.5",
            _meta: { "posthog.code/modelHarness": "codex" },
          },
          {
            name: "GPT-6 Astra",
            value: "gpt-6-astra",
            _meta: {
              "posthog.code/modelHarness": "codex",
              "posthog.code/restrictedModel": true,
            },
          },
        ],
      },
    ],
  } as unknown as SessionConfigOption;
}

async function openSub(user: ReturnType<typeof userEvent.setup>, name: RegExp) {
  const trigger = await screen.findByRole("menuitem", { name });
  await user.click(trigger);
  // The submenu opens on a Base UI timer that RTL's act-wrapped waitFor never
  // flushes in jsdom, so poll with plain sleeps instead of findByRole.
  for (let attempt = 0; attempt < 100; attempt++) {
    if (screen.queryAllByRole("menuitemradio").length > 0) return;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error("submenu did not open");
}

describe("PiModelSelector", () => {
  it("offers the full catalog and reports picks by gateway model id", async () => {
    const onChange = vi.fn();
    const onGatewayModelSelect = vi.fn();
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    render(
      <PiModelSelector
        models={piModels}
        currentModel={piModels[0]}
        onChange={onChange}
        modelOption={groupedModelOption()}
        onGatewayModelSelect={onGatewayModelSelect}
      />,
    );

    await user.click(
      screen.getByRole("button", { name: "Model: Claude Opus 5" }),
    );
    await openSub(user, /^Model/);
    fireEvent.click(
      await screen.findByRole("menuitemradio", { name: "GPT-5.5" }),
    );

    expect(onGatewayModelSelect).toHaveBeenCalledWith("gpt-5.5");
    expect(onGatewayModelSelect).toHaveBeenCalledTimes(1);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("shows the cost multiplier beside a restricted model lock", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    render(
      <PiModelSelector
        models={piModels}
        currentModel={piModels[0]}
        onChange={vi.fn()}
        modelOption={groupedModelOption()}
        onGatewayModelSelect={vi.fn()}
      />,
    );

    await user.click(
      screen.getByRole("button", { name: "Model: Claude Opus 5" }),
    );
    await openSub(user, /^Model/);

    const astra = await screen.findByRole("menuitemradio", {
      name: "GPT-6 Astra",
    });
    expect(within(astra).getByText("5×")).toBeInTheDocument();
    expect(astra.querySelector("svg")).toBeInTheDocument();
  });
});
