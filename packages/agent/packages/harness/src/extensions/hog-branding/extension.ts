import * as path from "node:path";
import type {
  ExtensionAPI,
  ExtensionContext,
  ExtensionFactory,
  Theme,
} from "@earendil-works/pi-coding-agent";
import {
  keyHint,
  keyText,
  rawKeyHint,
  VERSION,
} from "@earendil-works/pi-coding-agent";
import type { Component } from "@earendil-works/pi-tui";
import {
  HOG_APP_NAME as BRAND_NAME,
  HOG_BRAND_TAGLINE as BRAND_TAGLINE,
} from "./brand-env";

export interface HogBrandingOptions {
  /** Override the version string shown in the header (defaults to the pi package version). */
  version?: string;
}

type ExpandableHeaderComponent = Component & {
  setExpanded(expanded: boolean): void;
  dispose?(): void;
};

function brandLine(theme: Theme, version: string): string {
  const brand = theme.bold(theme.fg("accent", BRAND_NAME));
  const tagline = theme.fg("dim", ` (${BRAND_TAGLINE})`);
  const versionText = theme.fg("dim", ` v${version}`);
  return `${brand}${tagline}${versionText}`;
}

function createHeaderComponent(
  theme: Theme,
  version: string,
): ExpandableHeaderComponent {
  let expanded = false;
  const logo = brandLine(theme, version);

  const compactInstructions = [
    keyHint("app.interrupt", "to interrupt"),
    rawKeyHint(`${keyText("app.clear")} twice`, "to exit"),
    rawKeyHint("/", "for commands"),
    rawKeyHint("!", "to run bash"),
    keyHint("app.tools.expand", "more"),
  ].join(theme.fg("muted", " · "));

  // One hint per array entry, NOT joined into a single "\n"-separated
  // string: `render()` must return one terminal line per array element, and
  // handing back one big multi-line string as a single "line" makes the TUI
  // measure the whole block's width as one line — tripping its overflow
  // guard (`Rendered line N exceeds terminal width`) even though each
  // individual hint easily fits.
  const expandedInstructions = [
    keyHint("app.interrupt", "to interrupt"),
    keyHint("app.clear", "to clear"),
    rawKeyHint(`${keyText("app.clear")} twice`, "to exit"),
    keyHint("app.exit", "to exit (empty)"),
    keyHint("app.suspend", "to suspend"),
    keyHint("app.thinking.cycle", "to cycle thinking level"),
    rawKeyHint(
      `${keyText("app.model.cycleForward")}/${keyText("app.model.cycleBackward")}`,
      "to cycle models",
    ),
    keyHint("app.model.select", "to select model"),
    keyHint("app.tools.expand", "to collapse"),
    rawKeyHint("/", "for commands"),
    rawKeyHint("!", "to run bash"),
    rawKeyHint("!!", "to run bash (no context)"),
  ];

  const compactHint = theme.fg(
    "dim",
    `Press ${keyText("app.tools.expand")} to show full startup help.`,
  );

  return {
    render(_width: number): string[] {
      return expanded
        ? [logo, ...expandedInstructions]
        : [logo, compactInstructions, compactHint];
    },
    invalidate(): void {},
    setExpanded(next: boolean): void {
      expanded = next;
    },
  };
}

function terminalTitle(ctx: ExtensionContext): string {
  const cwdBasename = path.basename(ctx.sessionManager.getCwd());
  const sessionName = ctx.sessionManager.getSessionName();
  return sessionName
    ? `${BRAND_NAME} - ${sessionName} - ${cwdBasename}`
    : `${BRAND_NAME} - ${cwdBasename}`;
}

// pi's own interactive mode calls its internal `updateTerminalTitle()`
// (which uses the built-in `π`/`APP_TITLE` prefix) synchronously right
// after `session_start`/`session_info_changed` extension handlers resolve,
// so setting the title inline here loses the race and gets stomped on the
// same tick. Deferring to the next tick lets our title win.
function setBrandedTitle(ctx: ExtensionContext): void {
  const title = terminalTitle(ctx);
  ctx.ui.setTitle(title);
  setTimeout(() => ctx.ui.setTitle(title), 0);
}

export function createHogBrandingExtension(
  options: HogBrandingOptions = {},
): ExtensionFactory {
  return async (pi: ExtensionAPI) => {
    pi.on("session_start", async (_event, ctx) => {
      setBrandedTitle(ctx);
      if (ctx.mode !== "tui") return;
      const version = options.version ?? VERSION;
      ctx.ui.setHeader((_tui, theme) => createHeaderComponent(theme, version));
    });

    pi.on("session_info_changed", async (_event, ctx) => {
      setBrandedTitle(ctx);
    });
  };
}

export default function hogBranding(pi: ExtensionAPI): void | Promise<void> {
  return createHogBrandingExtension()(pi);
}
