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

let detected: "light" | "dark" = "dark";

// The theme found at startup, for colours pi's own theme does not cover.
export function rememberTheme(theme: "light" | "dark"): void {
  detected = theme;
}

export function terminalTheme(): "light" | "dark" {
  return detected;
}
