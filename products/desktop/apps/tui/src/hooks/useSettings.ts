import type {
  CodexAuthTokens,
  UserCodexIntegration,
} from "@posthog/api-client/posthog-client";
import { useRef, useState } from "react";
import { chatgptAccount, chatgptLogin, chatgptLogout } from "../chatgpt";
import { claudeOnPath } from "../claudeSetup";
import {
  clearClaudeToken,
  loadClaudeToken,
  saveClaudeToken,
} from "../claudeToken";
import { CLOUD_AUTH_PATH, connectCodexCloud } from "../codexCloud";
import { messageOf } from "../errors";
import { openUrl } from "../openUrl";
import { loadPrefs, savePrefs } from "../prefs";
import { type SettingsView, settingsKey, settingsView } from "../settings";

// PostHog's copy of the user's ChatGPT account, for cloud Codex runs.
export interface CodexCloudClient {
  get(): Promise<UserCodexIntegration>;
  connect(tokens: CodexAuthTokens): Promise<UserCodexIntegration>;
  disconnect(): Promise<void>;
}

const cloudAccountOf = (integration: UserCodexIntegration): string | null =>
  integration.status === "connected"
    ? (integration.email ?? "ChatGPT")
    : integration.status === "reauth_required"
      ? `${integration.email ?? "ChatGPT"} (needs reconnecting)`
      : null;

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
// `runSetup` runs `claude setup-token` on the terminal and returns the token; absent where the terminal cannot be handed over.
export function useSettings(
  codexCloud?: CodexCloudClient,
  runSetup?: () => Promise<string>,
  // Hears the Today row's switch, so the sidebar and main view follow it at once.
  onShowToday?: (on: boolean) => void,
): SettingsState {
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<SettingsView>(() =>
    settingsView({ billing: "posthog", account: null }),
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

  const browserLogin = (
    controller: AbortController,
    path?: string,
  ): Promise<string | null> =>
    chatgptLogin(
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
      path,
    );

  // The local login, or the cloud one: a second browser login whose tokens go to PostHog.
  const startLogin = async (cloud: boolean): Promise<void> => {
    const controller = new AbortController();
    login.current = controller;
    try {
      if (cloud) {
        if (!codexCloud) throw new Error("Sign in to PostHog first");
        const integration = await connectCodexCloud({
          login: async (path) => {
            await browserLogin(controller, path);
          },
          connect: (tokens) => codexCloud.connect(tokens),
          path: CLOUD_AUTH_PATH,
        });
        update({
          ...latest.current,
          cloudAccount: cloudAccountOf(integration),
          busy: false,
        });
      } else {
        const account = await browserLogin(controller);
        update({ ...latest.current, account, busy: false, index: 1 });
      }
    } catch (error) {
      if (!controller.signal.aborted)
        update({
          ...latest.current,
          busy: false,
          error: `${cloud ? "Connecting" : "Login"} failed: ${messageOf(error)}`,
        });
    } finally {
      if (login.current === controller) login.current = null;
    }
  };

  const setupToken = async (): Promise<void> => {
    try {
      if (!runSetup) throw new Error("The terminal cannot be handed over here");
      saveClaudeToken(await runSetup());
      update({ ...latest.current, hasToken: true, busy: false });
    } catch (error) {
      update({
        ...latest.current,
        busy: false,
        error: `Couldn't get a token: ${messageOf(error)}`,
      });
    }
  };

  return {
    open,
    view,
    toggle: () => {
      if (!open) {
        update(
          settingsView({
            billing: loadPrefs().billing,
            account: chatgptAccount(),
            hasToken: loadClaudeToken() !== null,
            canSetup: runSetup !== undefined && claudeOnPath(),
            showContext: loadPrefs().showContext,
            showToday: loadPrefs().showToday,
          }),
        );
        // The cloud account comes from the server, so its row fills in once the answer lands.
        codexCloud
          ?.get()
          .then((integration) =>
            update({
              ...latest.current,
              cloudAccount: cloudAccountOf(integration),
            }),
          )
          .catch(() => {});
      }
      setOpen(!open);
    },
    onKey: (sequence) => {
      const { view: next, effect } = settingsKey(latest.current, sequence);
      update(next);
      if (!effect) return;
      try {
        if (effect.kind === "saveToken") return saveClaudeToken(effect.token);
        if (effect.kind === "clearToken") return clearClaudeToken();
        if (effect.kind === "showContext")
          return savePrefs({ showContext: effect.on });
        if (effect.kind === "showToday") {
          savePrefs({ showToday: effect.on });
          onShowToday?.(effect.on);
          return;
        }
      } catch (error) {
        return update({
          ...next,
          error: `Couldn't save: ${messageOf(error)}`,
        });
      }
      if (effect.kind === "login") void startLogin(false);
      else if (effect.kind === "runSetupToken") void setupToken();
      else if (effect.kind === "connectCloud") void startLogin(true);
      else if (effect.kind === "disconnectCloud")
        codexCloud?.disconnect().catch((error) =>
          update({
            ...latest.current,
            error: `Couldn't disconnect: ${messageOf(error)}`,
          }),
        );
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
