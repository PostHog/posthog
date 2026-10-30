import { CHATGPT_MODEL } from "./chatgpt";
import type { Sheet } from "./sheet";

// Who pays for a chat's model use. It decides the agent too: pi on PostHog, Claude Code on a Claude plan,
// Codex in the cloud on a ChatGPT plan, and pi on the ChatGPT model on this machine.
export type Billing = "posthog" | "chatgpt" | "anthropic";

export const BILLINGS: Billing[] = ["posthog", "chatgpt", "anthropic"];

export type CloudHarness = "pi" | "claude" | "codex";

const CLOUD_HARNESS: Record<Billing, CloudHarness> = {
  posthog: "pi",
  chatgpt: "codex",
  anthropic: "claude",
};

const LABELS: Record<Billing, { label: string; detail: string }> = {
  posthog: { label: "PostHog", detail: "pi on PostHog credits" },
  chatgpt: {
    label: "ChatGPT",
    detail: "Your ChatGPT plan: pi here, Codex in the cloud",
  },
  anthropic: {
    label: "Anthropic",
    detail: "Your Claude plan: Claude Code here and in the cloud",
  },
};

export function cloudHarnessFor(billing: Billing): CloudHarness {
  return CLOUD_HARNESS[billing];
}

export const localHarnessFor = (billing: Billing): "pi" | "claude" =>
  billing === "anthropic" ? "claude" : "pi";

export type LocalStart =
  | { harness: "pi"; model?: string }
  | { harness: "claude" };

// What a local chat starts with, or why it cannot start.
export function localStartFor(
  billing: Billing,
  state: { chatgptAccount: string | null },
): LocalStart {
  if (localHarnessFor(billing) === "claude") return { harness: "claude" };
  if (billing === "chatgpt") {
    if (!state.chatgptAccount)
      throw new Error(
        "Log in to ChatGPT in settings (Ctrl+;), or pick another /billing",
      );
    return { harness: "pi", model: CHATGPT_MODEL };
  }
  return { harness: "pi" };
}

const NOTICES: Record<Billing, string> = {
  posthog: "New chats run on PostHog credits",
  chatgpt: "New chats use your ChatGPT subscription",
  anthropic: "New chats use your Anthropic subscription",
};

export const billingNotice = (billing: Billing): string => NOTICES[billing];

// What the plan still needs before a chat can run on it; null when it is ready.
export function billingBlocker(
  billing: Billing,
  state: { chatgptAccount: string | null; claudeToken: boolean },
): string | null {
  if (billing === "chatgpt" && !state.chatgptAccount)
    return "Log in to ChatGPT in settings (Ctrl+;) first";
  if (billing === "anthropic" && !state.claudeToken)
    return "Add your Claude token in settings (Ctrl+;) first";
  return null;
}

export function billingSheet(current: Billing): Sheet {
  return {
    title: "What new chats run on",
    description: "Chats already open keep their agent.",
    items: BILLINGS.map((billing) => ({
      ...LABELS[billing],
      current: billing === current,
    })),
    footer: "Enter to select · Esc to cancel",
  };
}
