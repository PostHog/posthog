import { useRef, useState } from "react";
import { chatgptAccount, chatgptLogin, chatgptLogout } from "../chatgpt";
import { messageOf } from "../errors";
import { openUrl } from "../openUrl";
import { loadPrefs, savePrefs } from "../prefs";
import { type SettingsView, settingsKey, settingsView } from "../settings";

export interface SettingsState {
  open: boolean;
  view: SettingsView;
  toggle: () => void;
  // Raw key sequences while the settings are open.
  onKey: (sequence: string) => void;
}

interface Asked {
  resolve: (text: string) => void;
  reject: (error: Error) => void;
}

// The full-screen settings: each change is saved as it is made, so closing loses nothing.
export function useSettings(): SettingsState {
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<SettingsView>(() =>
    settingsView(false, null),
  );
  // Keys arrive in bursts before React renders, so each one reads the view the last one left.
  const latest = useRef(view);
  const update = (next: SettingsView): void => {
    latest.current = next;
    setView(next);
  };
  // The login's open question, and the login itself, so Esc can stop either.
  const asked = useRef<Asked | null>(null);
  const login = useRef<AbortController | null>(null);

  const startLogin = async (): Promise<void> => {
    const controller = new AbortController();
    login.current = controller;
    try {
      const account = await chatgptLogin(
        {
          openUrl,
          prompt: (message, signal) =>
            new Promise<string>((resolve, reject) => {
              asked.current = { resolve, reject };
              update({ ...latest.current, prompt: message, draft: "" });
              signal?.addEventListener("abort", () => {
                if (asked.current?.resolve !== resolve) return;
                asked.current = null;
                update({ ...latest.current, prompt: null, draft: null });
                reject(new Error("Login cancelled"));
              });
            }),
        },
        controller.signal,
      );
      update({ ...latest.current, account, busy: false, index: 1 });
    } catch (error) {
      if (!controller.signal.aborted)
        update({
          ...latest.current,
          busy: false,
          error: `Login failed: ${messageOf(error)}`,
        });
    } finally {
      if (login.current === controller) login.current = null;
    }
  };

  return {
    open,
    view,
    toggle: () => {
      if (!open)
        update(settingsView(loadPrefs().localChatgptPlan, chatgptAccount()));
      setOpen(!open);
    },
    onKey: (sequence) => {
      const { view: next, effect } = settingsKey(latest.current, sequence);
      update(next);
      if (!effect) return;
      if (effect.kind === "setPlan") savePrefs({ localChatgptPlan: effect.on });
      else if (effect.kind === "login") void startLogin();
      else if (effect.kind === "answer") {
        asked.current?.resolve(effect.text);
        asked.current = null;
      } else if (effect.kind === "cancel") {
        asked.current?.reject(new Error("Login cancelled"));
        asked.current = null;
        login.current?.abort();
      } else if (effect.kind === "logout")
        chatgptLogout().catch((error) =>
          update({
            ...latest.current,
            error: `Couldn't log out: ${messageOf(error)}`,
          }),
        );
      else setOpen(false);
    },
  };
}
