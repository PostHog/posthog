import type { Billing } from "./billing";
import { isValidClaudeSetupToken } from "./claudeToken";
import { isTyping } from "./composer";
import { editQuery } from "./search";
import { sheetKey } from "./sheet";

// The settings screen: the ChatGPT login and the Claude token that /billing's plans run on.
export interface SettingsView {
  billing: Billing;
  // Who is logged in to ChatGPT; null when nobody is.
  account: string | null;
  hasToken: boolean;
  index: number;
  // A login is running, so its row takes no second Enter.
  busy: boolean;
  // A question the login asks; null while it asks nothing.
  prompt: string | null;
  // The answer, or a Claude token, being typed; null while nothing is.
  draft: string | null;
  error: string | null;
}

export type SettingsItem = "login" | "logout" | "token" | "removeToken";

export type SettingsEffect =
  | { kind: "login" }
  | { kind: "answer"; text: string }
  | { kind: "cancel" }
  | { kind: "logout" }
  | { kind: "saveToken"; token: string }
  | { kind: "clearToken" }
  | { kind: "close" };

export const TOKEN_HINT =
  "Paste the full token from `claude setup-token`. It starts with sk-ant-oat01-.";

export function settingsView(saved: {
  billing: Billing;
  account: string | null;
  hasToken?: boolean;
}): SettingsView {
  return {
    billing: saved.billing,
    account: saved.account,
    hasToken: saved.hasToken ?? false,
    index: 0,
    busy: false,
    prompt: null,
    draft: null,
    error: null,
  };
}

export function settingsItems(view: SettingsView): SettingsItem[] {
  return [
    view.account ? "logout" : "login",
    "token",
    ...(view.hasToken ? ["removeToken" as const] : []),
  ];
}

// The view after a key, and what it asks the app to do.
export function settingsKey(
  view: SettingsView,
  sequence: string,
): { view: SettingsView; effect?: SettingsEffect } {
  const key = sheetKey(sequence);
  const items = settingsItems(view);
  if (view.draft !== null) {
    const answering = view.prompt !== null;
    if (key?.kind === "dismiss")
      return answering
        ? {
            view: { ...view, prompt: null, draft: null, busy: false },
            effect: { kind: "cancel" },
          }
        : { view: { ...view, draft: null, error: null } };
    if (key?.kind === "choose") {
      const text = view.draft.trim();
      if (answering)
        return {
          view: { ...view, prompt: null, draft: null },
          effect: { kind: "answer", text },
        };
      if (!isValidClaudeSetupToken(text))
        return { view: { ...view, error: TOKEN_HINT } };
      return {
        view: { ...view, draft: null, error: null, hasToken: true },
        effect: { kind: "saveToken", token: text },
      };
    }
    return {
      view: {
        ...view,
        draft: editQuery(view.draft, sequence).trim(),
        error: null,
      },
    };
  }
  if (key?.kind === "dismiss") return { view, effect: { kind: "close" } };
  if (key?.kind === "up" || key?.kind === "down") {
    const step = key.kind === "down" ? 1 : -1;
    const index = Math.max(0, Math.min(items.length - 1, view.index + step));
    return { view: { ...view, index } };
  }
  if (key?.kind === "choose") {
    const item = items[view.index];
    if (item === "logout")
      return {
        view: { ...view, account: null },
        effect: { kind: "logout" },
      };
    if (item === "token") return { view: { ...view, draft: "" } };
    if (item === "removeToken")
      return {
        view: { ...view, hasToken: false, index: items.indexOf("token") },
        effect: { kind: "clearToken" },
      };
    if (view.busy) return { view };
    return {
      view: { ...view, busy: true, error: null },
      effect: { kind: "login" },
    };
  }
  // Typing anywhere else starts pasting a Claude token.
  if (isTyping(sequence))
    return {
      view: {
        ...view,
        index: items.indexOf("token"),
        draft: editQuery("", sequence).trim(),
        error: null,
      },
    };
  return { view };
}
