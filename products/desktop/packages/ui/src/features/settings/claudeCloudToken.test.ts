import { describe, expect, it } from "vitest";
import {
  claudeTokenExpiryDays,
  claudeTokenExpiryWarning,
  findClaudeSetupToken,
} from "./claudeCloudToken";

const NOW = new Date("2026-03-01T12:00:00Z");
const TOKEN = "sk-ant-oat01-Fake_test-token-0123456789abcdefghijABCDEFGHIJ-AA";

describe("claudeTokenExpiryDays", () => {
  it.each([
    [null, null],
    ["not a date", null],
    ["2026-03-31T12:00:00Z", 30],
    ["2026-03-01T13:00:00Z", 1],
    ["2026-03-01T12:00:00Z", 0],
    ["2026-02-20T12:00:00Z", 0],
  ])("returns the days left before %s", (expiresAt, days) => {
    expect(claudeTokenExpiryDays(expiresAt, NOW)).toBe(days);
  });
});

describe("claudeTokenExpiryWarning", () => {
  it.each([
    ["connected", "2026-03-16T12:00:00Z", null],
    [
      "connected",
      "2026-03-15T12:00:00Z",
      "Your Claude token expires in about 14 days. Create a new token before this date.",
    ],
    [
      "connected",
      "2026-03-02T11:00:00Z",
      "Your Claude token expires in about 1 day. Create a new token before this date.",
    ],
    [
      "connected",
      "2026-02-28T12:00:00Z",
      "Your Claude token expires today. Create a new token now.",
    ],
    ["connected", null, null],
    ["reauth_required", "2026-03-02T11:00:00Z", null],
  ] as const)(
    "warns about a %s token that expires at %s",
    (status, expiresAt, warning) => {
      expect(
        claudeTokenExpiryWarning(
          {
            status,
            connected_at: "2025-03-01T12:00:00Z",
            expires_at: expiresAt,
          },
          NOW,
        ),
      ).toBe(warning);
    },
  );
});

describe("findClaudeSetupToken", () => {
  it.each([
    [
      "a token on one line",
      `Your OAuth token:\r\n\r\n${TOKEN}\r\n\r\nStore this token securely.\r\n`,
    ],
    [
      "a token that the CLI wraps across indented lines",
      `Your OAuth token:\r\n\r\n  ${TOKEN.slice(0, 30)}\r\n  ${TOKEN.slice(30, 50)}\r\n  ${TOKEN.slice(50)}\r\n\r\nStore this token securely.\r\n`,
    ],
    [
      "a token inside color codes, after an older frame",
      `\x1b[2K\x1b[1Ask-ant-oat01-short\r\n\x1b]8;;https://example.com\x07link\x1b]8;;\x07\r\n\x1b[32m${TOKEN}\x1b[39m\r\nexport CLAUDE_CODE_OAUTH_TOKEN=<token>\r\n`,
    ],
  ])("finds %s", (_name, output) => {
    expect(findClaudeSetupToken(output)).toBe(TOKEN);
  });

  it.each([
    ["no token", "Login failed. Try again.\r\n"],
    ["a truncated token", "sk-ant-oat01-tooShort\r\n"],
  ])("returns null for %s", (_name, output) => {
    expect(findClaudeSetupToken(output)).toBeNull();
  });
});
