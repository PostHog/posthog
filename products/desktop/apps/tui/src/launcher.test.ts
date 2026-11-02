import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const root = join(__dirname, "..");

describe("posthog-tui launcher", () => {
  it("prints its version and exits before the app starts, so a release can smoke the installed bin", () => {
    const { version } = JSON.parse(
      readFileSync(join(root, "package.json"), "utf8"),
    );
    const out = execFileSync(
      "node",
      [join(root, "posthog-tui.mjs"), "--version"],
      {
        encoding: "utf8",
        env: { ...process.env, HOME: "/nonexistent" },
        timeout: 10_000,
      },
    );
    expect(out.trim()).toBe(version);
  });
});
