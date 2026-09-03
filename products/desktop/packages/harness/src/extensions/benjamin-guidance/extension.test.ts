import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { afterEach, describe, expect, test, vi } from "vitest";
import {
  appendBenjaminGuidance,
  BENJAMIN_INSTRUCTION,
  BENJAMIN_UPSTREAM_COMMIT,
  isBenjaminEnabled,
} from "./extension";
import { assertMitLicense } from "./validation";

const MARKER = "BENJAMIN-PLUS MODE ACTIVE";

const lock = JSON.parse(
  readFileSync(
    new URL("./benjamin/benjamin.lock.json", import.meta.url),
    "utf8",
  ),
) as { commit: string; sha256: string };

describe("Benjamin guidance", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  describe("isBenjaminEnabled", () => {
    test("is off when POSTHOG_BENJAMIN is unset", () => {
      expect(isBenjaminEnabled({})).toBe(false);
    });

    test.each([["1"], ["true"], ["TRUE"], [" 1 "]])("is on for %j", (value) => {
      expect(isBenjaminEnabled({ POSTHOG_BENJAMIN: value })).toBe(true);
    });

    test.each([[""], ["0"], ["false"], ["yes"], ["on"]])(
      "is off for %j",
      (value) => {
        expect(isBenjaminEnabled({ POSTHOG_BENJAMIN: value })).toBe(false);
      },
    );
  });

  describe("appendBenjaminGuidance", () => {
    test("appends the instruction when enabled", () => {
      const result = appendBenjaminGuidance("base instructions", {
        POSTHOG_BENJAMIN: "1",
      });
      expect(result.startsWith("base instructions\n\n")).toBe(true);
      expect(result).toContain(MARKER);
    });

    test("returns instructions unchanged when unset", () => {
      expect(appendBenjaminGuidance("base instructions", {})).toBe(
        "base instructions",
      );
    });

    test("does not leave a leading separator when instructions are empty", () => {
      expect(
        appendBenjaminGuidance("", { POSTHOG_BENJAMIN: "1" }).startsWith(
          MARKER,
        ),
      ).toBe(true);
    });
  });

  describe("vendored instruction", () => {
    test("matches the sha256 recorded in benjamin.lock.json", () => {
      const digest = createHash("sha256")
        .update(Buffer.from(BENJAMIN_INSTRUCTION, "utf8"))
        .digest("hex");
      expect(digest).toBe(lock.sha256);
    });

    test("reports a short prefix of the pinned upstream commit", () => {
      expect(lock.commit.startsWith(BENJAMIN_UPSTREAM_COMMIT)).toBe(true);
    });
  });

  describe("sync license guard", () => {
    test("rejects a license that would escape the banner comment", () => {
      const mitLicense = [
        "MIT License",
        "Permission is hereby granted, free of charge, to any person obtaining a copy",
        'THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.',
      ].join("\n");
      expect(() => assertMitLicense(mitLicense)).not.toThrow();
      expect(() =>
        assertMitLicense(`${mitLicense}\n*/ globalThis.pwned = true; /*`),
      ).toThrow(/block-comment terminator/);
    });
  });
});
