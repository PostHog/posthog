import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import {
  subscriptionModelAccess,
  type WorkspaceModeForAccess,
} from "@posthog/ui/features/settings/adapterSubscription";
import {
  type AgentAdapter,
  useSettingsStore,
} from "@posthog/ui/features/settings/settingsStore";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { type ReactElement, useState } from "react";
import { within } from "storybook/test";
import { ReasoningLevelSelector } from "./ReasoningLevelSelector";

const harnessOption = (
  harness: AgentAdapter,
  value: string,
  name: string,
): { value: string; name: string; _meta: Record<string, unknown> } => ({
  value,
  name,
  _meta: { "posthog.code/modelHarness": harness },
});

const ANTHROPIC_MODELS = [
  harnessOption("claude", "claude-fable-5", "Claude Fable 5"),
  harnessOption("claude", "claude-opus-5", "Claude Opus 5"),
  harnessOption("claude", "claude-opus-4-8", "Claude Opus 4.8"),
  harnessOption("claude", "claude-sonnet-5", "Claude Sonnet 5"),
];

const OPENAI_MODELS = [
  harnessOption("codex", "gpt-5.6-sol", "GPT-5.6 Sol"),
  harnessOption("codex", "gpt-5.6-terra", "GPT-5.6 Terra"),
  harnessOption("codex", "gpt-5.5", "GPT-5.5"),
];

const ZAI_MODELS = [
  harnessOption("claude", "zai-org/glm-5.3-flash", "GLM-5.3 Flash"),
  harnessOption("claude", "zai-org/glm-5.3", "GLM-5.3"),
];

const MOONSHOT_MODELS = [
  harnessOption("claude", "moonshotai/kimi-k3", "Kimi K3"),
];

const DEEPSEEK_MODELS = [
  harnessOption(
    "claude",
    "deepseek-ai/deepseek-v4-flash-0731",
    "DeepSeek V4 Flash",
  ),
];

function groupedModelOption(currentValue: string): SessionConfigOption {
  return {
    type: "select",
    id: "model",
    name: "Model",
    category: "model",
    currentValue,
    options: [
      { group: "anthropic", name: "Anthropic", options: ANTHROPIC_MODELS },
      { group: "openai", name: "OpenAI", options: OPENAI_MODELS },
      { group: "zai-org", name: "Z.ai", options: ZAI_MODELS },
      { group: "moonshotai", name: "Moonshot AI", options: MOONSHOT_MODELS },
      { group: "deepseek-ai", name: "DeepSeek", options: DEEPSEEK_MODELS },
    ],
  } as unknown as SessionConfigOption;
}

function effortOption(currentValue: string): SessionConfigOption {
  return {
    type: "select",
    id: "effort",
    name: "Effort",
    category: "thought_level",
    currentValue,
    options: [
      { name: "Low", value: "low" },
      { name: "Medium", value: "medium" },
      {
        name: "High",
        value: "high",
        _meta: { "posthog.code/defaultOption": true },
      },
      { name: "Extra High", value: "xhigh" },
      { name: "Max", value: "max" },
    ],
  } as unknown as SessionConfigOption;
}

function contextWindowOption(): SessionConfigOption {
  return {
    type: "select",
    id: "context_window",
    name: "Context Window",
    category: "_context_window",
    currentValue: "1m",
    options: [
      { name: "200k", value: "200k" },
      {
        name: "1M",
        value: "1m",
        _meta: { "posthog.code/defaultOption": true },
      },
    ],
  } as unknown as SessionConfigOption;
}

function Harness({
  workspaceMode,
  subscriptionOn = false,
  billingAdapter = "claude",
}: {
  workspaceMode?: WorkspaceModeForAccess;
  /** Provider picked in the Billing menu; true reveals the logged-out login note. */
  subscriptionOn?: boolean;
  /** Adapter whose Billing submenu is shown. */
  billingAdapter?: AgentAdapter;
}): ReactElement {
  const [, setAdapter] = useState<AgentAdapter>("claude");
  const [model, setModel] = useState("claude-opus-5");
  const [effort, setEffort] = useState("medium");

  // The submenu reads the real useAdapterSubscription hook, which reads the
  // settings store; the modelAccess prop below only gates the model list.
  const store = useSettingsStore.getState();
  store.setClaudeModelAccess(
    billingAdapter === "claude" && subscriptionOn
      ? "own-subscription"
      : "posthog-gateway",
  );
  store.setCodexModelAccess(
    billingAdapter === "codex" && subscriptionOn
      ? "own-subscription"
      : "posthog-gateway",
  );

  return (
    <div className="flex h-[520px] items-end p-2">
      <ReasoningLevelSelector
        thoughtOption={effortOption(effort)}
        modelOption={groupedModelOption(model)}
        adapter={billingAdapter}
        contextWindowOption={contextWindowOption()}
        onChange={setEffort}
        onModelChange={setModel}
        onAdapterChange={setAdapter}
        onHarnessModelChange={(harness, nextModel) => {
          setAdapter(harness);
          setModel(nextModel);
        }}
        onConfigOptionChange={() => {}}
        showBillingMenu={workspaceMode !== undefined}
        workspaceMode={workspaceMode}
        // Storybook never resolves the subscription status query, so the
        // provider counts as not logged in; the store write above picks the
        // billing shown in the submenu.
        modelAccess={
          workspaceMode === undefined
            ? undefined
            : subscriptionModelAccess(
                {
                  flagEnabled: true,
                  subscriptionOn,
                  status: undefined,
                  loggedIn: false,
                  loginState: "unknown",
                  needsConnection: subscriptionOn,
                  setSubscriptionOn: () => {},
                },
                workspaceMode,
              )
        }
      />
    </div>
  );
}

const meta: Meta<typeof Harness> = {
  title: "Sessions/ReasoningLevelSelector",
  component: Harness,
};

export default meta;
type Story = StoryObj<typeof Harness>;

export const Default: Story = {};

export const GroupedModelSubmenu: Story = {
  play: async ({ canvas, canvasElement, userEvent }): Promise<void> => {
    const body = within(canvasElement.ownerDocument.body);
    await userEvent.click(
      canvas.getByRole("button", { name: /Model and reasoning/ }),
    );
    await userEvent.click(
      await body.findByRole("button", { name: "Advanced" }),
    );
    await userEvent.hover(await body.findByText("Model"));
    await body.findByText("GPT-5.6 Sol");
  },
};

async function openBillingSubmenu(
  canvas: ReturnType<typeof within>,
  canvasElement: HTMLElement,
  userEvent: {
    click: (el: HTMLElement) => Promise<void>;
    hover: (el: HTMLElement) => Promise<void>;
  },
): Promise<void> {
  const body = within(canvasElement.ownerDocument.body);
  await userEvent.click(
    canvas.getByRole("button", { name: /Model and reasoning/ }),
  );
  // An off-ladder combo opens straight on the Advanced view, with no toggle.
  const advanced = body.queryByRole("button", { name: "Advanced" });
  if (advanced) {
    await userEvent.click(advanced);
  }
  await userEvent.click(await body.findByRole("menuitem", { name: /Billing/ }));
}

function BillingHarnessLocal(): ReactElement {
  return <Harness workspaceMode="local" />;
}

function BillingHarnessCloud(): ReactElement {
  return <Harness workspaceMode="cloud" />;
}

function BillingHarnessLoginPrompt(): ReactElement {
  return <Harness workspaceMode="local" subscriptionOn />;
}

export const LocalBilling: StoryObj<typeof BillingHarnessLocal> = {
  render: () => <BillingHarnessLocal />,
  play: async ({ canvas, canvasElement, userEvent }): Promise<void> => {
    await openBillingSubmenu(canvas, canvasElement, userEvent);
    const body = within(canvasElement.ownerDocument.body);
    await body.findByRole("menuitemradio", { name: "PostHog" });
    await body.findByRole("menuitemradio", { name: "Anthropic" });
  },
};

export const LoginPromptBilling: StoryObj<typeof BillingHarnessLoginPrompt> = {
  render: () => <BillingHarnessLoginPrompt />,
  play: async ({ canvas, canvasElement, userEvent }): Promise<void> => {
    await openBillingSubmenu(canvas, canvasElement, userEvent);
    const body = within(canvasElement.ownerDocument.body);
    await body.findByRole("button", { name: "Log in to Claude Code" });
    await body.findByText(
      (_, element) =>
        element?.textContent ===
        "Log in to Claude Code to use Anthropic billing.",
    );
  },
};

function BillingHarnessCodexLoginPrompt(): ReactElement {
  return (
    <Harness workspaceMode="local" subscriptionOn billingAdapter="codex" />
  );
}

export const LoginPromptBillingCodex: StoryObj<
  typeof BillingHarnessCodexLoginPrompt
> = {
  render: () => <BillingHarnessCodexLoginPrompt />,
  play: async ({ canvas, canvasElement, userEvent }): Promise<void> => {
    await openBillingSubmenu(canvas, canvasElement, userEvent);
    const body = within(canvasElement.ownerDocument.body);
    await body.findByRole("menuitemradio", { name: "OpenAI" });
    await body.findByRole("button", { name: "Connect ChatGPT" });
    await body.findByText(
      (_, element) =>
        element?.textContent === "Connect ChatGPT to use OpenAI billing.",
    );
  },
};

export const CloudBilling: StoryObj<typeof BillingHarnessCloud> = {
  render: () => <BillingHarnessCloud />,
  play: async ({ canvas, canvasElement, userEvent }): Promise<void> => {
    await openBillingSubmenu(canvas, canvasElement, userEvent);
    const body = within(canvasElement.ownerDocument.body);
    const provider = await body.findByRole("menuitemradio", {
      name: "Anthropic",
    });
    await userEvent.hover(provider);
    await body.findByText(/Anthropic billing only works/);
  },
};
