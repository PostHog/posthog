import { initTheme } from "@earendil-works/pi-coding-agent";

// The terminal's answer to an OSC 11 background query: ESC ] 11 ; rgb:RRRR/GGGG/BBBB, then BEL or ST.
const BACKGROUND_REPLY = new RegExp(
  `${"\u001b"}\\]11;rgb:([0-9a-f]+)/([0-9a-f]+)/([0-9a-f]+)`,
  "i",
);
export const BACKGROUND_QUERY = "\u001b]11;?\u0007";

export function themeFromBackgroundReply(
  reply: string,
): "light" | "dark" | null {
  const match = BACKGROUND_REPLY.exec(reply);
  if (!match) return null;
  const [red, green, blue] = match
    .slice(1)
    .map((hex) => Number.parseInt(hex, 16) / (16 ** hex.length - 1));
  const luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue;
  return luminance >= 0.5 ? "light" : "dark";
}

// Asks the terminal for its background before Ink takes stdin; terminals that stay silent get dark.
export function detectTheme(
  stdin: NodeJS.ReadStream = process.stdin,
  stdout: NodeJS.WriteStream = process.stdout,
  timeoutMs = 200,
): Promise<"light" | "dark"> {
  if (!stdin.isTTY || !stdout.isTTY) return Promise.resolve("dark");
  return new Promise((resolve) => {
    let reply = "";
    const done = (theme: "light" | "dark"): void => {
      clearTimeout(timer);
      stdin.off("data", onData);
      stdin.setRawMode(false);
      stdin.pause();
      resolve(theme);
    };
    const onData = (data: Buffer): void => {
      reply += data.toString("utf8");
      const theme = themeFromBackgroundReply(reply);
      if (theme) done(theme);
    };
    const timer = setTimeout(() => done("dark"), timeoutMs);
    stdin.setRawMode(true);
    stdin.on("data", onData);
    stdout.write(BACKGROUND_QUERY);
  });
}

// PostHog orange (#F54E00), for modes that should stand out, such as shell commands.
export const orange = (text: string): string =>
  `\u001b[38;2;245;78;0m${text}\u001b[39m`;

// The theme pi draws with, kept so the TUI's own colours can follow it.
// On globalThis because a hot swap of src/ re-runs this module but not the startup that detected the theme.
const kept = globalThis as { __posthogTuiTheme?: "light" | "dark" };

export function applyTheme(theme: "light" | "dark"): void {
  kept.__posthogTuiTheme = theme;
  initTheme(theme);
}

// The fill behind a message the user sent: a step off the terminal's background, lighter than pi's own.
export const userMessageBackground = (): string =>
  kept.__posthogTuiTheme === "light"
    ? "\u001b[48;2;242;242;242m"
    : "\u001b[48;2;38;39;46m";
