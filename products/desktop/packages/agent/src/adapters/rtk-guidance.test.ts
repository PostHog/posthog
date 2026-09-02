import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterAll, beforeAll, describe, expect, test } from "vitest";
import {
  GIT_COMPRESSIBLE_SUBCOMMANDS,
  RTK_PLAIN_COMMANDS,
} from "./claude/session/rtk";
import { appendRtkGuidanceForCodex, buildRtkGuidance } from "./rtk-guidance";

describe("rtk guidance for codex", () => {
  let dir: string;
  let binary: string;

  beforeAll(() => {
    dir = fs.mkdtempSync(path.join(os.tmpdir(), "rtk-guidance-test-"));
    binary = path.join(dir, "rtk");
    fs.writeFileSync(binary, "#!/bin/sh\n");
  });

  afterAll(() => {
    fs.rmSync(dir, { recursive: true, force: true });
  });

  describe("buildRtkGuidance", () => {
    // The guidance must advertise exactly the Claude hook's eligibility sets,
    // so the token-usage cohorts stay comparable across adapters.
    test("advertises every command the Claude hook rewrites", () => {
      const guidance = buildRtkGuidance("/usr/local/bin/rtk");
      for (const command of RTK_PLAIN_COMMANDS) {
        expect(guidance).toContain(command);
      }
      for (const sub of GIT_COMPRESSIBLE_SUBCOMMANDS) {
        expect(guidance).toContain(sub);
      }
    });

    test("uses the resolved binary path in the examples", () => {
      const guidance = buildRtkGuidance("/usr/local/bin/rtk");
      expect(guidance).toContain("`/usr/local/bin/rtk git status`");
    });

    // A desktop install can resolve a path with spaces; unquoted it would
    // split into multiple shell tokens and every guided command would fail.
    test("shell-quotes a binary path containing spaces", () => {
      const guidance = buildRtkGuidance("/Apps/My Tools/rtk");
      expect(guidance).toContain("`'/Apps/My Tools/rtk' git status`");
      expect(guidance).not.toContain("`/Apps/My Tools/rtk git status`");
    });

    // Parity with the Claude hook's exclusion: prefixing commit/push would
    // hide the leading `git` token from the cloud signed-commit guard.
    test("forbids prefixing git commit and git push", () => {
      const guidance = buildRtkGuidance("rtk");
      expect(guidance).toContain("Never prefix `git commit`, `git push`");
    });
  });

  describe("appendRtkGuidanceForCodex", () => {
    test("appends guidance when rtk is on PATH", () => {
      const result = appendRtkGuidanceForCodex("base instructions", {
        PATH: dir,
      });
      expect(result.startsWith("base instructions\n\n")).toBe(true);
      expect(result).toContain("rtk command-output compression");
      expect(result).toContain(binary);
    });

    // POSTHOG_RTK=0 is set per run from the cloud kill-switch flag; it must
    // silence the guidance too, which is why the gate is resolveRtkPrefix
    // rather than detectRtkBinary.
    test.each([["0"], ["false"]])(
      "returns instructions unchanged when POSTHOG_RTK is %s",
      (value) => {
        expect(
          appendRtkGuidanceForCodex("base instructions", {
            POSTHOG_RTK: value,
            PATH: dir,
          }),
        ).toBe("base instructions");
      },
    );

    test("returns instructions unchanged when rtk is not installed", () => {
      expect(
        appendRtkGuidanceForCodex("base instructions", {
          PATH: "/nonexistent",
        }),
      ).toBe("base instructions");
    });

    test("does not leave a leading separator when instructions are empty", () => {
      const result = appendRtkGuidanceForCodex("", { PATH: dir });
      expect(result.startsWith("## rtk")).toBe(true);
    });
  });
});
