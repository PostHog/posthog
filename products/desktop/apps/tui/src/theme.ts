import { initTheme } from "@earendil-works/pi-coding-agent";

// The terminal's answer to an OSC 11 background query: ESC ] 11 ; rgb:RRRR/GGGG/BBBB, then BEL or ST.
const BACKGROUND_REPLY = new RegExp(
  `${"\u001b"}\\]11;rgb:([0-9a-f]+)/([0-9a-f]+)/([0-9a-f]+)`,
  "i",
);
export const BACKGROUND_QUERY = "\u001b]11;?\u0007";

export type Rgb = [number, number, number];

// The terminal's background as 0-255 channels, from its reply to the query.
export function backgroundFromReply(reply: string): Rgb | null {
  const match = BACKGROUND_REPLY.exec(reply);
  if (!match) return null;
  const [red, green, blue] = match
    .slice(1)
    .map((hex) =>
      Math.round((Number.parseInt(hex, 16) / (16 ** hex.length - 1)) * 255),
    );
  return [red, green, blue];
}

const themeOf = ([red, green, blue]: Rgb): "light" | "dark" =>
  (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255 >= 0.5
    ? "light"
    : "dark";

export function themeFromBackgroundReply(
  reply: string,
): "light" | "dark" | null {
  const background = backgroundFromReply(reply);
  return background ? themeOf(background) : null;
}

// Asks the terminal for its background before Ink takes stdin; null when it stays silent.
export function detectBackground(
  stdin: NodeJS.ReadStream = process.stdin,
  stdout: NodeJS.WriteStream = process.stdout,
  timeoutMs = 200,
): Promise<Rgb | null> {
  if (!stdin.isTTY || !stdout.isTTY) return Promise.resolve(null);
  return new Promise((resolve) => {
    let reply = "";
    const done = (background: Rgb | null): void => {
      clearTimeout(timer);
      stdin.off("data", onData);
      stdin.setRawMode(false);
      stdin.pause();
      resolve(background);
    };
    const onData = (data: Buffer): void => {
      reply += data.toString("utf8");
      const background = backgroundFromReply(reply);
      if (background) done(background);
    };
    const timer = setTimeout(() => done(null), timeoutMs);
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
const kept = globalThis as {
  __posthogTuiTheme?: "light" | "dark";
  __posthogTuiBackground?: Rgb;
};

export function applyTheme(theme: "light" | "dark"): void {
  kept.__posthogTuiTheme = theme;
  initTheme(theme);
}

// Follows the terminal's own background: light or dark for pi, and the colour fills step off.
export function applyBackground(background: Rgb): void {
  kept.__posthogTuiBackground = background;
  applyTheme(themeOf(background));
}

// A step from the terminal's background towards its text: lighter on a dark theme, darker on a light one.
// Fills built this way sit just off whatever background the terminal uses.
function tint(amount: number): Rgb {
  const light = kept.__posthogTuiTheme === "light";
  const background =
    kept.__posthogTuiBackground ?? (light ? [255, 255, 255] : [0, 0, 0]);
  const towards = light ? 0 : 255;
  return background.map((channel) =>
    Math.round(channel + (towards - channel) * amount),
  ) as Rgb;
}

const hexOf = (rgb: Rgb): string =>
  `#${rgb.map((channel) => channel.toString(16).padStart(2, "0")).join("")}`;

// The fill behind a message the user sent.
export const userMessageBackground = (): string =>
  `\u001b[48;2;${tint(0.07).join(";")}m`;

// The fill behind the selected sidebar row: a stronger step, so it reads as picked without inverse video's glare.
export const selectionBackground = (): string => hexOf(tint(0.16));

// PostHog blue (#1D4AFF), for what should catch the eye: notices, inline code and links.
// Dark terminals get a lighter step of it, since the brand blue is hard to read on black.
export const posthogBlue = (): string =>
  kept.__posthogTuiTheme === "light" ? "#1D4AFF" : "#6384FF";

export const blue = (text: string): string => {
  const hex = posthogBlue();
  const [red, green, blueValue] = [1, 3, 5].map((at) =>
    Number.parseInt(hex.slice(at, at + 2), 16),
  );
  return `\u001b[38;2;${red};${green};${blueValue}m${text}\u001b[39m`;
};
