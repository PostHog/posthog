import { editQuery } from "./search";
import { sheetKey } from "./sheet";

// The settings screen: the ChatGPT plan switch for local chats, and the login it runs on.
export interface SettingsView {
  planOn: boolean;
  // Who is logged in to ChatGPT; null when nobody is.
  account: string | null;
  index: number;
  // A login is running, so its row takes no second Enter.
  busy: boolean;
  // A question the login asks, and the answer being typed; both null while it asks nothing.
  prompt: string | null;
  draft: string | null;
  error: string | null;
}

export type SettingsItem = "plan" | "login" | "logout";

export type SettingsEffect =
  | { kind: "setPlan"; on: boolean }
  | { kind: "login" }
  | { kind: "answer"; text: string }
  | { kind: "cancel" }
  | { kind: "logout" }
  | { kind: "close" };

export function settingsView(
  planOn: boolean,
  account: string | null,
): SettingsView {
  return {
    planOn,
    account,
    index: 0,
    busy: false,
    prompt: null,
    draft: null,
    error: null,
  };
}

export function settingsItems(view: SettingsView): SettingsItem[] {
  return ["plan", view.account ? "logout" : "login"];
}

// The view after a key, and what it asks the app to do.
export function settingsKey(
  view: SettingsView,
  sequence: string,
): { view: SettingsView; effect?: SettingsEffect } {
  const key = sheetKey(sequence);
  const items = settingsItems(view);
  if (view.draft !== null) {
    if (key?.kind === "dismiss")
      return {
        view: { ...view, prompt: null, draft: null, busy: false },
        effect: { kind: "cancel" },
      };
    if (key?.kind === "choose")
      return {
        view: { ...view, prompt: null, draft: null },
        effect: { kind: "answer", text: view.draft.trim() },
      };
    return {
      view: { ...view, draft: editQuery(view.draft, sequence).trim() },
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
    if (item === "plan")
      return {
        view: { ...view, planOn: !view.planOn },
        effect: { kind: "setPlan", on: !view.planOn },
      };
    if (item === "logout")
      return {
        view: { ...view, account: null },
        effect: { kind: "logout" },
      };
    if (view.busy) return { view };
    return {
      view: { ...view, busy: true, error: null },
      effect: { kind: "login" },
    };
  }
  return { view };
}
