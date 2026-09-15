import { resolve } from "node:path";
import {
  type AgentSession,
  type AgentSessionRuntime,
  getAgentDir,
  SessionManager,
} from "@earendil-works/pi-coding-agent";
import { createHarnessRuntime } from "@posthog/harness";
import {
  createPiRuntimeTrustResolver,
  readPiProjectTrust,
} from "@posthog/harness/project-trust";
import {
  appendTranscriptError,
  projectSessionMessages,
  projectTranscriptEvent,
  type TranscriptItem,
} from "./transcript.js";

export interface CliState {
  transcript: readonly TranscriptItem[];
  status: string;
  promptActive: boolean;
}

export interface HarnessControllerOptions {
  cwd: string;
  continueSession: boolean;
}

export class HarnessController {
  private runtime: AgentSessionRuntime | undefined;
  private session: AgentSession | undefined;
  private unsubscribe: (() => void) | undefined;
  private state: CliState = {
    transcript: [],
    status: "Ready",
    promptActive: false,
  };

  constructor(
    private readonly options: HarnessControllerOptions,
    private readonly onStateChange: (state: CliState) => void,
    private readonly onTurnSettled: () => void,
    private readonly onExit: () => void,
  ) {}

  get isPromptActive(): boolean {
    return this.state.promptActive;
  }

  async start(): Promise<void> {
    const cwd = resolve(this.options.cwd);
    const agentDir = getAgentDir();
    const trust = readPiProjectTrust(cwd, cwd, agentDir);
    const sessionManager = this.options.continueSession
      ? SessionManager.continueRecent(cwd)
      : SessionManager.create(cwd);

    this.runtime = await createHarnessRuntime({
      cwd,
      sessionManager,
      projectTrusted: createPiRuntimeTrustResolver(
        cwd,
        trust.trusted,
        agentDir,
      ),
    });
    this.runtime.setRebindSession(async (session) => {
      await this.rebindSession(session);
    });
    await this.rebindSession(this.runtime.session);

    if (
      this.runtime.diagnostics.some((diagnostic) => diagnostic.type === "error")
    ) {
      this.updateState({
        transcript: appendTranscriptError(
          this.state.transcript,
          "Some extensions did not load. Use /reload, then try again.",
        ),
      });
    }
  }

  async submit(prompt: string, onAccepted: () => void): Promise<void> {
    const session = this.session;
    if (!session || this.state.promptActive || !prompt.trim()) {
      return;
    }

    this.updateState({ promptActive: true, status: "Working" });
    let accepted = false;

    try {
      await session.prompt(prompt, {
        preflightResult: (success) => {
          if (success) {
            accepted = true;
            onAccepted();
          }
        },
      });
    } catch {
      this.updateState({
        transcript: appendTranscriptError(
          this.state.transcript,
          "The request could not start. Check hog /login, then try again.",
        ),
        status: "Ready",
      });
    } finally {
      if (!accepted || session.isIdle) {
        this.settleTurn();
      }
    }
  }

  async abortOrExit(): Promise<"aborted" | "exit"> {
    const session = this.session;
    if (!session || (session.isIdle && !this.state.promptActive)) {
      return "exit";
    }

    this.updateState({ status: "Stopping" });
    try {
      await session.abort();
    } catch {
      this.updateState({
        transcript: appendTranscriptError(
          this.state.transcript,
          "Could not stop the request. Try Ctrl+C again.",
        ),
        status: "Ready",
      });
      this.onTurnSettled();
    }
    return "aborted";
  }

  async dispose(): Promise<void> {
    this.unsubscribe?.();
    this.unsubscribe = undefined;
    await this.runtime?.dispose();
    this.runtime = undefined;
    this.session = undefined;
  }

  private async rebindSession(session: AgentSession): Promise<void> {
    const runtime = this.runtime;
    if (!runtime) {
      return;
    }

    this.unsubscribe?.();
    this.session = session;
    await session.bindExtensions({
      mode: "print",
      commandContextActions: {
        waitForIdle: () => session.waitForIdle(),
        newSession: async (newSessionOptions) =>
          runtime.newSession(newSessionOptions),
        fork: async (entryId, forkOptions) => {
          const result = await runtime.fork(entryId, forkOptions);
          return { cancelled: result.cancelled };
        },
        navigateTree: async (targetId, navigateOptions) => {
          const result = await session.navigateTree(targetId, {
            summarize: navigateOptions?.summarize,
            customInstructions: navigateOptions?.customInstructions,
            replaceInstructions: navigateOptions?.replaceInstructions,
            label: navigateOptions?.label,
          });
          return { cancelled: result.cancelled };
        },
        switchSession: async (sessionPath, switchOptions) =>
          runtime.switchSession(sessionPath, switchOptions),
        reload: async () => {
          await session.reload();
        },
      },
      abortHandler: () => {
        void session.abort();
      },
      shutdownHandler: this.onExit,
      onError: () => {
        this.updateState({
          transcript: appendTranscriptError(
            this.state.transcript,
            "An extension failed. Use /reload, then try again.",
          ),
        });
      },
    });

    this.updateState({
      transcript: projectSessionMessages(session.state.messages),
      status: "Ready",
      promptActive: false,
    });
    this.unsubscribe = session.subscribe((event) => {
      this.updateState({
        transcript: projectTranscriptEvent(this.state.transcript, event),
      });
      if (event.type === "agent_settled") {
        this.settleTurn();
      }
    });
    this.onTurnSettled();
  }

  private settleTurn(): void {
    if (!this.state.promptActive && this.state.status === "Ready") {
      return;
    }

    this.updateState({ promptActive: false, status: "Ready" });
    this.onTurnSettled();
  }

  private updateState(change: Partial<CliState>): void {
    this.state = { ...this.state, ...change };
    this.onStateChange(this.state);
  }
}
