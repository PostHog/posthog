import { stat } from "node:fs/promises";
import { resolve } from "node:path";
import {
  BoxRenderable,
  CliRenderEvents,
  type CliRenderer,
  createCliRenderer,
  defaultTextareaKeyBindings,
  type KeyEvent,
  ScrollBoxRenderable,
  TextareaRenderable,
  TextRenderable,
} from "@opentui/core";
import { type CliState, HarnessController } from "./controller.js";
import type { TranscriptItem } from "./transcript.js";

interface CliOptions {
  cwd: string;
  continueSession: boolean;
  help: boolean;
}

function usage(): string {
  return [
    "Usage: hog-tui [--cwd <path>] [--continue] [--help]",
    "",
    "Start a terminal session for the PostHog harness.",
    "",
    "Options:",
    "  --cwd <path>  Set the working directory.",
    "  --continue    Continue the most recent session for the working directory.",
    "  --help        Show this help.",
    "",
    "Controls:",
    "  Enter         Send the prompt.",
    "  Shift+Enter   Insert a new line.",
    "  Ctrl+C        Stop the active turn, or exit when idle.",
  ].join("\n");
}

function parseOptions(args: string[]): CliOptions {
  let cwd = process.cwd();
  let continueSession = false;
  let help = false;

  for (let index = 0; index < args.length; index += 1) {
    const argument = args[index];
    if (argument === "--cwd") {
      const value = args[index + 1];
      if (!value || value.startsWith("-")) {
        throw new Error("--cwd requires a path.");
      }
      cwd = value;
      index += 1;
      continue;
    }
    if (argument === "--continue") {
      continueSession = true;
      continue;
    }
    if (argument === "--help") {
      help = true;
      continue;
    }
    throw new Error(`Unknown option: ${argument}`);
  }

  return { cwd: resolve(cwd), continueSession, help };
}

function formatTranscriptItem(item: TranscriptItem): string {
  if (item.kind === "user") {
    return `You\n${item.text}`;
  }
  if (item.kind === "assistant") {
    return `Assistant\n${item.text}`;
  }
  if (item.kind === "tool") {
    return `${item.name}: ${item.state}`;
  }
  if (item.kind === "error") {
    return `Error\n${item.text}`;
  }
  return item.text;
}

class CliView {
  private readonly transcript: TextRenderable;
  private readonly status: TextRenderable;
  private readonly composer: TextareaRenderable;
  private submit: (() => void) | undefined;

  constructor(renderer: CliRenderer) {
    const layout = new BoxRenderable(renderer, {
      height: "100%",
      flexDirection: "column",
      padding: 1,
      gap: 1,
    });
    const header = new TextRenderable(renderer, {
      content: "hog-tui",
      height: 1,
      fg: "#f9b65b",
    });
    const transcriptBox = new ScrollBoxRenderable(renderer, {
      flexGrow: 1,
      border: true,
      borderColor: "#666666",
      padding: 1,
      stickyScroll: true,
      stickyStart: "bottom",
      scrollY: true,
    });
    this.transcript = new TextRenderable(renderer, {
      content: "Start a conversation.",
      wrapMode: "word",
    });
    this.status = new TextRenderable(renderer, {
      content: "Ready",
      height: 1,
      fg: "#aaaaaa",
    });
    const composerBox = new BoxRenderable(renderer, {
      height: 4,
      border: true,
      borderColor: "#666666",
      focusedBorderColor: "#f9b65b",
    });
    this.composer = new TextareaRenderable(renderer, {
      height: "100%",
      placeholder: "Write a prompt",
      wrapMode: "word",
      keyBindings: [
        ...defaultTextareaKeyBindings,
        { name: "return", action: "submit" },
        { name: "return", shift: true, action: "newline" },
      ],
      onSubmit: () => this.submit?.(),
    });

    transcriptBox.add(this.transcript);
    layout.add(header);
    layout.add(transcriptBox);
    composerBox.add(this.composer);
    layout.add(this.status);
    layout.add(composerBox);
    renderer.root.add(layout);
  }

  setSubmit(submit: () => void): void {
    this.submit = submit;
  }

  render(state: CliState): void {
    this.transcript.content = state.transcript.length
      ? state.transcript.map(formatTranscriptItem).join("\n\n")
      : "Start a conversation.";
    this.status.content = state.status;
  }

  prompt(): string {
    return this.composer.plainText;
  }

  clearPrompt(): void {
    this.composer.editBuffer.setText("");
  }

  focusComposer(): void {
    this.composer.focus();
  }

  showStartupError(): void {
    this.transcript.content =
      "Error\nCould not start the session. Check hog /login, then try again.";
    this.status.content = "Session unavailable";
  }
}

async function ensureDirectory(cwd: string): Promise<void> {
  const cwdStat = await stat(cwd).catch((error: unknown) => {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      throw new Error(`Working directory does not exist: ${cwd}`);
    }
    throw error;
  });
  if (!cwdStat.isDirectory()) {
    throw new Error(`Working directory is not a directory: ${cwd}`);
  }
}

export async function main(args: string[]): Promise<void> {
  let options: CliOptions;
  try {
    options = parseOptions(args);
  } catch (error) {
    process.stderr.write(
      `${error instanceof Error ? error.message : "Invalid command."}\n\n${usage()}\n`,
    );
    process.exitCode = 1;
    return;
  }

  if (options.help) {
    process.stdout.write(`${usage()}\n`);
    return;
  }

  try {
    await ensureDirectory(options.cwd);
  } catch (error) {
    process.stderr.write(
      `${error instanceof Error ? error.message : "Invalid working directory."}\n`,
    );
    process.exitCode = 1;
    return;
  }

  const renderer = await createCliRenderer({
    screenMode: "alternate-screen",
    exitOnCtrlC: false,
    clearOnShutdown: true,
    consoleMode: "disabled",
  });
  const view = new CliView(renderer);
  let controller: HarnessController | undefined;
  let resolveExit: (() => void) | undefined;
  const exit = new Promise<void>((resolveExitPromise) => {
    resolveExit = resolveExitPromise;
  });
  let exiting = false;
  const requestExit = (): void => {
    if (exiting) {
      return;
    }
    exiting = true;
    resolveExit?.();
  };
  const interrupt = (): void => {
    void (async () => {
      const result = controller ? await controller.abortOrExit() : "exit";
      if (result === "exit") {
        requestExit();
      }
    })();
  };
  const handleCtrlC = (event: KeyEvent): void => {
    if (event.name !== "c" || !event.ctrl) {
      return;
    }
    event.preventDefault();
    interrupt();
  };
  const handleSignal = (): void => requestExit();

  renderer.keyInput.on("keypress", handleCtrlC);
  renderer.on(CliRenderEvents.DESTROY, requestExit);
  process.once("SIGINT", interrupt);
  process.once("SIGTERM", handleSignal);
  process.once("SIGHUP", handleSignal);
  renderer.start();

  try {
    controller = new HarnessController(
      { cwd: options.cwd, continueSession: options.continueSession },
      (state) => view.render(state),
      () => view.focusComposer(),
      requestExit,
    );
    view.setSubmit(() => {
      void controller?.submit(view.prompt(), () => view.clearPrompt());
    });
    await controller.start();
    view.focusComposer();
    await exit;
  } catch {
    view.showStartupError();
    view.focusComposer();
    await exit;
  } finally {
    process.off("SIGINT", interrupt);
    process.off("SIGTERM", handleSignal);
    process.off("SIGHUP", handleSignal);
    renderer.keyInput.off("keypress", handleCtrlC);
    renderer.off(CliRenderEvents.DESTROY, requestExit);
    await controller?.dispose();
    renderer.destroy();
  }
}
