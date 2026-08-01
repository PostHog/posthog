import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import {
  DEFAULT_OPTION_META_KEY,
  OPTION_DOCS_URL_META_KEY,
} from "@posthog/shared";
import { Theme } from "@radix-ui/themes";
import { configure, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ReasoningLevelSelector } from "./ReasoningLevelSelector";

// Menu open/close and submenu reveals ride animations that starve under
// parallel suite load; the default 1s async timeout flakes.
configure({ asyncUtilTimeout: 5000 });

const openUrlInBrowser = vi.hoisted(() => vi.fn());
vi.mock("@posthog/ui/utils/browser", () => ({ openUrlInBrowser }));
vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: () => true,
}));

const ultracodeDocsUrl = "https://code.claude.com/docs/en/workflows";

function thoughtOption(
  overrides?: Partial<SessionConfigOption>,
): SessionConfigOption {
  return {
    type: "select",
    id: "effort",
    name: "Effort",
    category: "thought_level",
    currentValue: "high",
    options: [
      { name: "Low", value: "low" },
      {
        name: "High",
        value: "high",
        _meta: { [DEFAULT_OPTION_META_KEY]: true },
      },
      { name: "Max", value: "max" },
      {
        name: "Ultracode",
        value: "ultracode",
        _meta: { [OPTION_DOCS_URL_META_KEY]: ultracodeDocsUrl },
      },
    ],
    ...overrides,
  } as unknown as SessionConfigOption;
}

function claudeModelOption(
  currentValue = "claude-opus-5",
): SessionConfigOption {
  return {
    type: "select",
    id: "model",
    name: "Model",
    category: "model",
    currentValue,
    options: [
      { name: "Claude Sonnet 5", value: "claude-sonnet-5" },
      { name: "Claude Opus 5", value: "claude-opus-5" },
      { name: "Claude Fable 5", value: "claude-fable-5" },
    ],
  } as unknown as SessionConfigOption;
}

function effortlessModelOption(): SessionConfigOption {
  return {
    type: "select",
    id: "model",
    name: "Model",
    category: "model",
    currentValue: "moonshotai/kimi-k3",
    options: [
      { name: "Claude Sonnet 5", value: "claude-sonnet-5" },
      { name: "Claude Opus 5", value: "claude-opus-5" },
      { name: "Kimi K3", value: "moonshotai/kimi-k3" },
    ],
  } as unknown as SessionConfigOption;
}

function contextOption(currentValue = "1m"): SessionConfigOption {
  return {
    type: "select",
    id: "context_window",
    name: "Context Window",
    currentValue,
    options: [
      { name: "200k", value: "200k" },
      { name: "1M", value: "1m", _meta: { [DEFAULT_OPTION_META_KEY]: true } },
    ],
  } as unknown as SessionConfigOption;
}

function fastOption(currentValue = "off"): SessionConfigOption {
  return {
    type: "select",
    id: "fast",
    name: "Fast Mode",
    currentValue,
    options: [
      { name: "On", value: "on" },
      { name: "Off", value: "off" },
    ],
  } as unknown as SessionConfigOption;
}

async function openAdvanced(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "Reasoning: High" }));
  await user.click(await screen.findByRole("button", { name: "Advanced" }));
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
  // The submenu opens on a Base UI timer that RTL's act-wrapped waitFor never
  // flushes in jsdom, so poll with plain sleeps instead of findByRole.
  for (let attempt = 0; attempt < 100; attempt++) {
    if (screen.queryAllByRole("menuitemradio").length > 0) return;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error("submenu did not open");
}

describe("ReasoningLevelSelector", () => {
  it("renders the active level as the trigger label", () => {
    render(
      <Theme>
        <ReasoningLevelSelector thoughtOption={thoughtOption()} />
      </Theme>,
    );
    expect(
      screen.getByRole("button", { name: "Reasoning: High" }),
    ).toBeInTheDocument();
  });

  it("opens on a Faster/Smarter slider without the option lists", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    render(
      <Theme>
        <ReasoningLevelSelector thoughtOption={thoughtOption()} />
      </Theme>,
    );

    await user.click(screen.getByRole("button", { name: "Reasoning: High" }));
    expect(await screen.findByRole("slider")).toBeInTheDocument();
    expect(screen.getByText("Faster ($)")).toBeInTheDocument();
    expect(screen.getByText("Smarter ($$$)")).toBeInTheDocument();
    expect(screen.queryByRole("menuitemradio")).not.toBeInTheDocument();
  });

  it("emits the raw value via onChange once the advanced menu closes", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    render(
      <Theme>
        <ReasoningLevelSelector
          thoughtOption={thoughtOption()}
          onChange={onChange}
        />
      </Theme>,
    );

    await openAdvanced(user);
    await openSub(user, /^Reasoning/);
    const lowItem = await screen.findByRole("menuitemradio", { name: "Low" });
    fireEvent.click(lowItem);

    await pollUntil(() => onChange.mock.calls.length > 0);
    expect(onChange).toHaveBeenCalledWith("low");
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("marks the adapter default level with a Default badge", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    render(
      <Theme>
        <ReasoningLevelSelector thoughtOption={thoughtOption()} />
      </Theme>,
    );

    await openAdvanced(user);
    await openSub(user, /^Reasoning/);
    const highItem = await screen.findByRole("menuitemradio", {
      name: /High/,
    });
    expect(highItem).toHaveTextContent("Default");
  });

  it("opens the docs link without selecting the level", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    render(
      <Theme>
        <ReasoningLevelSelector
          thoughtOption={thoughtOption()}
          onChange={onChange}
        />
      </Theme>,
    );

    await openAdvanced(user);
    await openSub(user, /^Reasoning/);
    const docsButton = await screen.findByRole("button", {
      name: "Learn more about Ultracode",
    });
    // Plain dispatch: user-event's pointer sequence can re-highlight the
    // parent item under suite load and swallow the click.
    fireEvent.click(docsButton);

    expect(openUrlInBrowser).toHaveBeenCalledWith(ultracodeDocsUrl);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("changes context window from its advanced submenu", async () => {
    const onConfigOptionChange = vi.fn();
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    render(
      <Theme>
        <ReasoningLevelSelector
          thoughtOption={thoughtOption()}
          contextWindowOption={contextOption()}
          fastModeOption={fastOption()}
          onConfigOptionChange={onConfigOptionChange}
        />
      </Theme>,
    );

    await openAdvanced(user);
    // Fast mode is the slider view's lightning toggle, not an advanced row.
    expect(
      screen.queryByRole("menuitem", { name: /Fast Mode/ }),
    ).not.toBeInTheDocument();
    await openSub(user, /Context Window/);
    fireEvent.click(await screen.findByRole("menuitemradio", { name: "200k" }));

    await pollUntil(() => onConfigOptionChange.mock.calls.length > 0);
    expect(onConfigOptionChange).toHaveBeenCalledWith("context_window", "200k");
    expect(onConfigOptionChange).toHaveBeenCalledTimes(1);
  });

  it("toggles fast mode from the slider view lightning button", async () => {
    const onConfigOptionChange = vi.fn();
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    render(
      <Theme>
        <ReasoningLevelSelector
          thoughtOption={thoughtOption()}
          adapter="claude"
          fastModeOption={fastOption("off")}
          onConfigOptionChange={onConfigOptionChange}
        />
      </Theme>,
    );

    await user.click(screen.getByRole("button", { name: "Reasoning: High" }));
    await user.click(
      await screen.findByRole("button", { name: "Toggle fast mode" }),
    );

    expect(onConfigOptionChange).toHaveBeenCalledWith("fast", "on");
  });

  it("resets effort and sections to their defaults", async () => {
    const onChange = vi.fn();
    const onConfigOptionChange = vi.fn();
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    render(
      <Theme>
        <ReasoningLevelSelector
          thoughtOption={thoughtOption({ currentValue: "max" })}
          contextWindowOption={contextOption("200k")}
          fastModeOption={fastOption("on")}
          onChange={onChange}
          onConfigOptionChange={onConfigOptionChange}
        />
      </Theme>,
    );

    await user.click(screen.getByRole("button", { name: "Reasoning: Max" }));
    await user.click(await screen.findByRole("button", { name: "Advanced" }));
    await user.click(await screen.findByText("Reset to default"));

    await pollUntil(() => onChange.mock.calls.length > 0);
    expect(onChange).toHaveBeenCalledWith("high");
    expect(onConfigOptionChange).toHaveBeenCalledWith("context_window", "1m");
    expect(onConfigOptionChange).toHaveBeenCalledWith("fast", "off");
  });

  it("opens on the ladder slider when the combo is a preset", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    render(
      <Theme>
        <ReasoningLevelSelector
          thoughtOption={thoughtOption()}
          modelOption={claudeModelOption("claude-sonnet-5")}
          adapter="claude"
        />
      </Theme>,
    );

    await user.click(
      screen.getByRole("button", { name: /Model and reasoning/ }),
    );
    expect(await screen.findByRole("slider")).toBeInTheDocument();
  });

  it("hides the slider when the combo is off the preset ladder", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    render(
      <Theme>
        <ReasoningLevelSelector
          thoughtOption={thoughtOption({ currentValue: "low" })}
          modelOption={claudeModelOption()}
          adapter="claude"
        />
      </Theme>,
    );

    await user.click(
      screen.getByRole("button", { name: /Model and reasoning/ }),
    );
    expect(
      await screen.findByRole("menuitem", { name: /^Reasoning/ }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("slider")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Back" }),
    ).not.toBeInTheDocument();
  });

  it("changes the model from its advanced submenu", async () => {
    const onModelChange = vi.fn();
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    render(
      <Theme>
        <ReasoningLevelSelector
          thoughtOption={thoughtOption()}
          modelOption={claudeModelOption("claude-sonnet-5")}
          adapter="claude"
          onModelChange={onModelChange}
        />
      </Theme>,
    );

    await user.click(
      screen.getByRole("button", { name: /Model and reasoning/ }),
    );
    await user.click(await screen.findByRole("button", { name: "Advanced" }));
    await openSub(user, /^Model/);
    fireEvent.click(
      await screen.findByRole("menuitemradio", { name: "Claude Opus 5" }),
    );

    await pollUntil(() => onModelChange.mock.calls.length > 0);
    expect(onModelChange).toHaveBeenCalledWith("claude-opus-5");
    expect(onModelChange).toHaveBeenCalledTimes(1);
  });

  it("moves the model and effort together on a ladder notch that changes both", async () => {
    const onChange = vi.fn();
    const onModelChange = vi.fn();
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    render(
      <Theme>
        <ReasoningLevelSelector
          thoughtOption={thoughtOption({ currentValue: "xhigh" })}
          modelOption={claudeModelOption("claude-opus-5")}
          adapter="claude"
          onChange={onChange}
          onModelChange={onModelChange}
        />
      </Theme>,
    );

    await user.click(
      screen.getByRole("button", { name: /Model and reasoning/ }),
    );
    const slider = await screen.findByRole("slider");
    fireEvent.keyDown(slider, { key: "ArrowRight" });

    await pollUntil(
      () =>
        onChange.mock.calls.length > 0 && onModelChange.mock.calls.length > 0,
    );
    expect(onModelChange).toHaveBeenCalledWith("claude-fable-5");
    expect(onChange).toHaveBeenCalledWith("max");
  });

  it("resets to the middle ladder notch, moving model and effort together", async () => {
    const onChange = vi.fn();
    const onModelChange = vi.fn();
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    render(
      <Theme>
        <ReasoningLevelSelector
          thoughtOption={thoughtOption({ currentValue: "max" })}
          modelOption={claudeModelOption("claude-fable-5")}
          adapter="claude"
          onChange={onChange}
          onModelChange={onModelChange}
        />
      </Theme>,
    );

    await user.click(
      screen.getByRole("button", { name: /Model and reasoning/ }),
    );
    await user.click(await screen.findByRole("button", { name: "Advanced" }));
    await user.click(await screen.findByText("Reset to default"));

    await pollUntil(() => onChange.mock.calls.length > 0);
    expect(onModelChange).toHaveBeenCalledWith("claude-opus-5");
    expect(onChange).toHaveBeenCalledWith("medium");
  });

  it.each([
    ["undefined option", undefined],
    ["non-select type", thoughtOption({ type: "boolean" })],
    ["empty options", thoughtOption({ options: [] })],
  ])("renders no trigger for %s", (_label, option) => {
    render(
      <ReasoningLevelSelector
        thoughtOption={option as SessionConfigOption | undefined}
      />,
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("keeps the model picker when the model has no reasoning levels", async () => {
    const onModelChange = vi.fn();
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    render(
      <Theme>
        <ReasoningLevelSelector
          modelOption={effortlessModelOption()}
          adapter="claude"
          onModelChange={onModelChange}
        />
      </Theme>,
    );

    await user.click(screen.getByRole("button", { name: "Model: Kimi K3" }));
    await openSub(user, /^Model/);
    fireEvent.click(
      await screen.findByRole("menuitemradio", { name: "Claude Opus 5" }),
    );

    await pollUntil(() => onModelChange.mock.calls.length > 0);
    expect(onModelChange).toHaveBeenCalledWith("claude-opus-5");
  });

  it("hides the reasoning submenu and slider for an effort-less model", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    render(
      <Theme>
        <ReasoningLevelSelector
          modelOption={effortlessModelOption()}
          adapter="claude"
        />
      </Theme>,
    );

    await user.click(screen.getByRole("button", { name: "Model: Kimi K3" }));
    expect(
      await screen.findByRole("menuitem", { name: /^Model/ }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("menuitem", { name: /^Reasoning/ }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("slider")).not.toBeInTheDocument();
  });

  it("drops the stale effort label when switching to an effort-less model", () => {
    const { rerender } = render(
      <Theme>
        <ReasoningLevelSelector
          thoughtOption={thoughtOption()}
          modelOption={claudeModelOption()}
          adapter="claude"
        />
      </Theme>,
    );

    rerender(
      <Theme>
        <ReasoningLevelSelector
          modelOption={effortlessModelOption()}
          adapter="claude"
        />
      </Theme>,
    );

    expect(
      screen.getByRole("button", { name: "Model: Kimi K3" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("High")).not.toBeInTheDocument();
  });

  it("shows a loading placeholder while the first config loads", () => {
    render(
      <Theme>
        <ReasoningLevelSelector isLoading />
      </Theme>,
    );

    expect(screen.getByRole("button", { name: /Loading/ })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
  });
});
