import { mkdtempSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  claudeTokenStore,
  clearClaudeToken,
  isValidClaudeSetupToken,
  loadClaudeToken,
  saveClaudeToken,
} from "./claudeToken";

const TOKEN = `sk-ant-oat01-${"x".repeat(40)}`;

describe("claudeToken", () => {
  const dirs: string[] = [];
  afterEach(() => {
    for (const dir of dirs.splice(0))
      rmSync(dir, { recursive: true, force: true });
  });

  it("saves the token for this user only and clears it", () => {
    const dir = mkdtempSync(join(tmpdir(), "posthog-tui-"));
    dirs.push(dir);
    const path = join(dir, "nested", "claude-token");
    expect(loadClaudeToken(path)).toBeNull();
    saveClaudeToken(` ${TOKEN}\n`, path);
    expect(loadClaudeToken(path)).toBe(TOKEN);
    expect(statSync(path).mode & 0o777).toBe(0o600);
    clearClaudeToken(path);
    expect(loadClaudeToken(path)).toBeNull();
  });

  it("hands the cloud engine the saved token", async () => {
    const dir = mkdtempSync(join(tmpdir(), "posthog-tui-"));
    dirs.push(dir);
    const path = join(dir, "claude-token");
    const store = claudeTokenStore(path);
    expect(await store.has()).toBe(false);
    await store.save(TOKEN);
    expect(await store.get("anyone")).toBe(TOKEN);
    await store.clear();
    expect(await store.get()).toBeNull();
  });

  it.each([
    [TOKEN, true],
    [`  ${TOKEN}  `, true],
    ["sk-ant-oat01-short", false],
    [`sk-ant-api03-${"x".repeat(40)}`, false],
    ["", false],
  ])("validates %s as %s", (value, valid) => {
    expect(isValidClaudeSetupToken(value)).toBe(valid);
  });
});
