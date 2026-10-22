import type { CloudRegion } from "@posthog/shared";
import {
  type Dispatch,
  type SetStateAction,
  useEffect,
  useRef,
  useState,
} from "react";
import { track } from "../analytics";
import { REGIONS } from "../auth";
import {
  BILLINGS,
  billingBlocker,
  billingNotice,
  billingSheet,
  chatgptLoginSheet,
  claudeTokenSheet,
  TOKEN_SHEET_RUN,
} from "../billing";
import { chatgptAccount, chatgptLogin } from "../chatgpt";
import { claudeOnPath } from "../claudeSetup";
import {
  isValidClaudeSetupToken,
  loadClaudeToken,
  saveClaudeToken,
} from "../claudeToken";
import { connectCodexCloud } from "../codexCloud";
import type { WelcomeStep } from "../components/Welcome";
import { messageOf } from "../errors";
import {
  activeWorkspace,
  findPane,
  focusPane,
  type LayoutState,
} from "../layout";
import { openUrl } from "../openUrl";
import { type ChatPlace, loadPrefs, savePrefs } from "../prefs";
import { TOKEN_HINT } from "../settings";
import type { Sheet } from "../sheet";
import type { Notice } from "./useNotice";
import type { CodexCloudClient } from "./useSettings";

export interface Account {
  // A first run's sign-in sheet, which goes on to ask who pays once signed in.
  welcome: (paneId: string) => void;
  // Where the first run's welcome is; null once it is done or dismissed.
  welcomeStep: WelcomeStep | null;
  openLoginSheet: (
    paneId: string,
    description: string,
    then?: (paneId: string) => void,
  ) => void;
  // Gets the Claude token the Anthropic plan needs and saves the plan with it.
  openClaudeTokenSheet: (
    paneId: string,
    draft: string,
    error: string | null,
  ) => void;
  // Signs in to ChatGPT in the browser: pi's own login for chats here, or the account PostHog keeps for cloud Codex runs.
  signInToChatgpt: (paneId: string, cloud: boolean, then: () => void) => void;
  openBillingSheet: (paneId: string) => void;
  signOut: (paneId: string) => void;
  // What each plan has signed in to, for `billingBlocker`.
  planState: () => Parameters<typeof billingBlocker>[1];
}

// Sign-in, who pays, and the sheets that get each plan its login; the first run's welcome walks through them.
export function useAccount({
  layout,
  setLayout,
  signedIn,
  placeFor,
  openModal,
  closeModal,
  notice: { flashNotice, showNotice },
  login,
  logout,
  onSignOut,
  runSetup,
  codexCloud,
}: {
  layout: LayoutState;
  setLayout: Dispatch<SetStateAction<LayoutState>>;
  signedIn: boolean;
  placeFor: (paneId: string) => ChatPlace;
  openModal: (
    paneId: string,
    sheet: Sheet,
    choose: (index: number, text?: string) => void,
    dismiss?: () => void,
  ) => void;
  closeModal: (paneId: string) => void;
  notice: Notice;
  login: (region: CloudRegion, onAuth: (url: string) => void) => Promise<void>;
  logout: () => void;
  // Clears what the screen held for the account that signed out.
  onSignOut: () => void;
  // Runs `claude setup-token` on the terminal and returns the token; absent where the terminal cannot be handed over.
  runSetup?: () => Promise<string>;
  // PostHog's copy of the user's ChatGPT account, for cloud Codex runs; absent while signed out.
  codexCloud?: CodexCloudClient;
}): Account {
  // The layout as of the last render: a sign-in swaps in the account's layout, so a sheet opened after it needs the pane it has.
  const latestLayout = useRef(layout);
  latestLayout.current = layout;

  // Whether PostHog holds a ChatGPT account for cloud Codex runs; false until the server has answered.
  const [chatgptCloud, setChatgptCloud] = useState(false);
  // The welcome's sheets were opened signed out, so they reach the client through this, not their closure.
  const latestCodexCloud = useRef(codexCloud);
  latestCodexCloud.current = codexCloud;
  useEffect(() => {
    let current = true;
    codexCloud
      ?.get()
      .then((integration) => {
        if (current) setChatgptCloud(integration.status === "connected");
      })
      .catch(() => {});
    return () => {
      current = false;
    };
  }, [codexCloud]);
  const planState = (): Parameters<typeof billingBlocker>[1] => ({
    chatgptAccount: chatgptAccount(),
    chatgptCloud,
    claudeToken: loadClaudeToken() !== null,
  });

  // The first run's welcome: its sheets report where it is, and the last one, or an Esc, ends it.
  // It starts from the first render, so the app's chrome never shows before the welcome does.
  const firstRun = !signedIn && !loadPrefs().welcomed;
  const [welcomeStep, setWelcomeStep] = useState<WelcomeStep | null>(
    firstRun ? "signIn" : null,
  );
  const welcoming = useRef(firstRun);
  const welcomeAt = (step: WelcomeStep): void => {
    if (welcoming.current) setWelcomeStep(step);
  };
  const endWelcome = (): void => {
    welcoming.current = false;
    setWelcomeStep(null);
  };

  const openLoginSheet = (
    paneId: string,
    description: string,
    then?: (paneId: string) => void,
  ): void => {
    welcomeAt("signIn");
    openModal(
      paneId,
      {
        title: "Sign in to PostHog",
        description,
        items: REGIONS.map((region) => ({ label: region.label })),
        footer: "Enter to open your browser · Esc to cancel",
      },
      (index) => {
        const region = REGIONS[index];
        showNotice("Finish signing in with your browser…");
        welcomeAt("signingIn");
        login(region.id, () => {}).then(
          () => {
            flashNotice(`Signed in to ${region.label}`);
            then?.(activeWorkspace(latestLayout.current).focusedPaneId);
          },
          (error: unknown) => {
            flashNotice(`Sign-in failed: ${messageOf(error)}`);
            // A welcome asks again, so a failed browser sign-in is not its end.
            if (welcoming.current) openLoginSheet(paneId, description, then);
          },
        );
      },
      endWelcome,
    );
  };

  // Gets the Claude token the Anthropic plan needs, by running `claude setup-token` or from a paste, and saves the plan with it.
  const openClaudeTokenSheet = (
    paneId: string,
    draft: string,
    error: string | null,
  ): void => {
    const run = runSetup && claudeOnPath() ? runSetup : undefined;
    const save = (token: string): void => {
      try {
        saveClaudeToken(token);
        savePrefs({ billing: "anthropic" });
        flashNotice(billingNotice("anthropic"));
      } catch (saveError) {
        flashNotice(`Couldn't save: ${messageOf(saveError)}`);
      }
      endWelcome();
    };
    welcomeAt("token");
    openModal(
      paneId,
      claudeTokenSheet(draft, error, run !== undefined),
      (index, token = "") => {
        if (index === TOKEN_SHEET_RUN && run) {
          run().then(save, (runError: unknown) =>
            openClaudeTokenSheet(
              paneId,
              "",
              `Couldn't get a token: ${messageOf(runError)}`,
            ),
          );
          return;
        }
        if (!isValidClaudeSetupToken(token))
          return openClaudeTokenSheet(paneId, token, TOKEN_HINT);
        save(token);
      },
      endWelcome,
    );
  };

  // A question pi's login asks, answered on a sheet; the browser answering it first closes the sheet.
  const askOnSheet = (
    paneId: string,
    question: string,
    signal?: AbortSignal,
  ): Promise<string> =>
    new Promise((resolve, reject) => {
      openModal(
        paneId,
        chatgptLoginSheet(question),
        (_, text = "") => resolve(text),
        () => reject(new Error("Sign-in cancelled")),
      );
      signal?.addEventListener("abort", () => {
        closeModal(paneId);
        reject(new Error("Sign-in cancelled"));
      });
    });

  const signInToChatgpt = (
    paneId: string,
    cloud: boolean,
    then: () => void,
  ): void => {
    welcomeAt("chatgpt");
    showNotice("Finish signing in to ChatGPT with your browser…");
    const ui = {
      openUrl,
      prompt: (question: string, signal?: AbortSignal) =>
        askOnSheet(paneId, question, signal),
    };
    const signal = new AbortController().signal;
    const client = latestCodexCloud.current;
    const signedIn = cloud
      ? client
        ? connectCodexCloud({
            login: async (path) => {
              await chatgptLogin(ui, signal, path);
            },
            connect: (tokens) => client.connect(tokens),
          }).then((integration) =>
            setChatgptCloud(integration.status === "connected"),
          )
        : Promise.reject(new Error("Sign in to PostHog first"))
      : chatgptLogin(ui, signal).then(() => {});
    signedIn.then(then, (error: unknown) => {
      flashNotice(`ChatGPT sign-in failed: ${messageOf(error)}`);
      endWelcome();
    });
  };

  const openBillingSheet = (paneId: string): void => {
    const here = { taskId: findPane(layout, paneId)?.taskId ?? null };
    welcomeAt("billing");
    openModal(
      paneId,
      billingSheet(loadPrefs().billing),
      (index) => {
        const billing = BILLINGS[index];
        const place = placeFor(paneId);
        const save = (): void => {
          savePrefs({ billing });
          flashNotice(billingNotice(billing), here);
          endWelcome();
        };
        const blocker = billingBlocker(billing, planState(), place);
        if (billing === "anthropic" && blocker)
          return openClaudeTokenSheet(paneId, "", null);
        // The plan's sign-in for where this pane's chats run; the other place asks for its own when first used.
        if (billing === "chatgpt" && blocker)
          return signInToChatgpt(paneId, place === "cloud", save);
        save();
      },
      endWelcome,
    );
  };

  // A session's workspaces stay in its account's layout file, so signing out only resets what the screen holds.
  const signOut = (paneId: string): void => {
    track("signed out");
    logout();
    onSignOut();
    flashNotice("Signed out");
    openLoginSheet(paneId, "Pick the PostHog you sign in to.");
  };

  // Signed out, the sign-in sheet opens by itself. A first run goes on to who pays; a run that was welcomed before,
  // or one that signed out, stops at the sign-in.
  const welcome = (paneId: string): void => {
    const first = !loadPrefs().welcomed;
    if (first) {
      savePrefs({ welcomed: true });
      track("welcomed");
      welcoming.current = true;
    }
    // The welcome's sheets take the keys of this pane.
    setLayout((current) => focusPane(current, paneId));
    openLoginSheet(
      paneId,
      "Pick the PostHog you sign in to. Your chats run on it.",
      first ? openBillingSheet : undefined,
    );
  };

  return {
    welcome,
    welcomeStep,
    openLoginSheet,
    openClaudeTokenSheet,
    signInToChatgpt,
    openBillingSheet,
    signOut,
    planState,
  };
}
