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
    detail: "Your Claude plan: Claude Code in the cloud",
  },
};

export function cloudHarnessFor(billing: Billing): CloudHarness {
  return CLOUD_HARNESS[billing];
}

// What a local pi chat starts with, or why it cannot start.
export function localStartFor(
  billing: Billing,
  state: { chatgptAccount: string | null },
): { model?: string } {
  if (billing === "anthropic")
    throw new Error("Claude plan chats run in the cloud for now: type /cloud");
  if (billing === "chatgpt") {
    if (!state.chatgptAccount)
      throw new Error(
        "Log in to ChatGPT in settings (Ctrl+;), or pick another /billing",
      );
    return { model: CHATGPT_MODEL };
  }
  return {};
}

export function billingSheet(current: Billing): Sheet {
  return {
    title: "Who pays for new chats",
    description: "Chats already open keep their agent.",
    items: BILLINGS.map((billing) => ({
      ...LABELS[billing],
      current: billing === current,
    })),
    footer: "Enter to select · Esc to cancel",
  };
}
