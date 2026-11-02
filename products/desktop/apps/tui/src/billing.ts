import { CHATGPT_MODEL } from "./chatgpt";
import type { ChatPlace } from "./prefs";
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
      throw new Error("Log in to ChatGPT first, or pick another /billing");
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

// What the plan still needs before a chat can run on it in `place`; null when it is ready.
// ChatGPT needs a login per place: pi's own here, and the account PostHog holds for cloud Codex runs.
export function billingBlocker(
  billing: Billing,
  state: {
    chatgptAccount: string | null;
    chatgptCloud: boolean;
    claudeToken: boolean;
  },
  place: ChatPlace = "cloud",
): string | null {
  if (billing === "chatgpt" && place === "cloud" && !state.chatgptCloud)
    return "Connect ChatGPT for cloud runs first";
  if (billing === "chatgpt" && place === "local" && !state.chatgptAccount)
    return "Log in to ChatGPT first";
  if (billing === "anthropic" && !state.claudeToken)
    return "Add your Claude token first";
  return null;
}

// A question pi's ChatGPT login asks, such as the code the browser shows, answered in its one item.
export function chatgptLoginSheet(question: string): Sheet {
  return {
    title: "Sign in to ChatGPT",
    description: question,
    items: [{ label: "Answer", input: { placeholder: "", text: "" } }],
    footer: "Enter to send · Esc to cancel the sign-in",
  };
}

export const TOKEN_SHEET_RUN = 0;
export const TOKEN_SHEET_PASTE = 1;

// Gets the Claude token the Anthropic plan runs on: by running `claude setup-token` here, or pasted into the second item.
export function claudeTokenSheet(
  draft: string,
  error: string | null,
  canRun: boolean,
): Sheet {
  return {
    title: "Add your Claude token",
    description:
      error ?? "Your Claude plan needs the token `claude setup-token` prints.",
    items: [
      {
        label: "Run claude setup-token",
        detail: canRun ? "Opens your browser" : undefined,
        disabled: canRun ? undefined : "install Claude Code first",
      },
      {
        label: "Paste a token",
        input: { placeholder: "sk-ant-oat01-…", text: draft },
      },
    ],
    footer: "Enter to choose · Esc to keep PostHog billing",
  };
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
