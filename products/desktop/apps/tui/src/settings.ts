import { isValidClaudeSetupToken } from "./claudeToken";
import { isTyping } from "./composer";
import { editQuery } from "./search";
import { sheetKey } from "./sheet";

// The settings screen: the Claude plan switch for local chats, and the token it runs on.
export interface SettingsView {
  planOn: boolean;
  hasToken: boolean;
  index: number;
  // The token being pasted; null while nothing is being typed.
  draft: string | null;
  error: string | null;
}

export type SettingsItem = "plan" | "token" | "remove";

export type SettingsEffect =
  | { kind: "setPlan"; on: boolean }
  | { kind: "saveToken"; token: string }
  | { kind: "clearToken" }
  | { kind: "close" };

export const TOKEN_HINT =
  "Paste the full token from the terminal. It starts with sk-ant-oat01-.";

export function settingsView(planOn: boolean, hasToken: boolean): SettingsView {
  return { planOn, hasToken, index: 0, draft: null, error: null };
}

export function settingsItems(view: SettingsView): SettingsItem[] {
  return view.hasToken ? ["plan", "token", "remove"] : ["plan", "token"];
}

// The view after a key, and what it asks the app to do. Typing anywhere starts pasting a token.
export function settingsKey(
  view: SettingsView,
  sequence: string,
): { view: SettingsView; effect?: SettingsEffect } {
  const key = sheetKey(sequence);
  const items = settingsItems(view);
  if (view.draft !== null) {
    if (key?.kind === "dismiss")
      return { view: { ...view, draft: null, error: null } };
    if (key?.kind === "choose") {
      const token = view.draft.trim();
      if (!isValidClaudeSetupToken(token))
        return { view: { ...view, error: TOKEN_HINT } };
      return {
        view: { ...view, draft: null, error: null, hasToken: true },
        effect: { kind: "saveToken", token },
      };
    }
    return {
      view: {
        ...view,
        draft: editQuery(view.draft, sequence).replace(/\s/g, ""),
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
    if (item === "plan")
      return {
        view: { ...view, planOn: !view.planOn },
        effect: { kind: "setPlan", on: !view.planOn },
      };
    if (item === "remove")
      return {
        view: { ...view, hasToken: false, index: 0 },
        effect: { kind: "clearToken" },
      };
    return { view: { ...view, draft: "" } };
  }
  if (isTyping(sequence))
    return {
      view: {
        ...view,
        index: items.indexOf("token"),
        draft: editQuery("", sequence).replace(/\s/g, ""),
        error: null,
      },
    };
  return { view };
}
