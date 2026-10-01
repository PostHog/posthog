import { describe, expect, it } from "vitest";
import { clipboardCommand, osc52 } from "./clipboard";

describe("osc52", () => {
  it("encodes text as UTF-8 base64 so any character survives", () => {
    const sequence = osc52("héllo 🦔\nworld");
    const payload = new RegExp(
      `^${"\u001b"}\\]52;c;([A-Za-z0-9+/=]+)${"\u0007"}$`,
    ).exec(sequence)?.[1];
    expect(Buffer.from(payload ?? "", "base64").toString("utf8")).toBe(
      "héllo 🦔\nworld",
    );
  });
});

describe("clipboardCommand", () => {
  it.each([
    ["macOS", "darwin", {}, ["pbcopy", []]],
    ["Wayland", "linux", { WAYLAND_DISPLAY: "wayland-0" }, ["wl-copy", []]],
    ["X11", "linux", { DISPLAY: ":0" }, ["xclip", ["-selection", "clipboard"]]],
    ["a Linux console with no display", "linux", {}, null],
    // Over SSH a local command would fill the remote machine's clipboard, so the terminal must do it.
    ["macOS over SSH", "darwin", { SSH_TTY: "/dev/ttys001" }, null],
    [
      "Linux over SSH",
      "linux",
      { SSH_CONNECTION: "1 2 3 4", DISPLAY: ":0" },
      null,
    ],
  ])("picks the right command on %s", (_, platform, env, expected) => {
    expect(clipboardCommand(platform as NodeJS.Platform, env)).toEqual(
      expected,
    );
  });
});
