import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { chatgptAccount, chatgptPlan } from "./chatgpt";

const jwt = (payload: object): string =>
  `h.${Buffer.from(JSON.stringify(payload)).toString("base64url")}.s`;

describe("chatgptAccount", () => {
  const dirs: string[] = [];
  afterEach(() => {
    for (const dir of dirs.splice(0))
      rmSync(dir, { recursive: true, force: true });
  });

  it("reads the email from the stored login, and null without one", () => {
    const dir = mkdtempSync(join(tmpdir(), "posthog-tui-"));
    dirs.push(dir);
    const path = join(dir, "auth.json");
    expect(chatgptAccount(path)).toBeNull();
    writeFileSync(path, JSON.stringify({ anthropic: { type: "oauth" } }));
    expect(chatgptAccount(path)).toBeNull();
    const access = jwt({
      "https://api.openai.com/profile": { email: "me@example.com" },
    });
    writeFileSync(
      path,
      JSON.stringify({ "openai-codex": { type: "oauth", access } }),
    );
    expect(chatgptAccount(path)).toBe("me@example.com");
    writeFileSync(
      path,
      JSON.stringify({ "openai-codex": { type: "oauth", access: "x" } }),
    );
    expect(chatgptAccount(path)).toBe("ChatGPT");
  });

  it("names the login's plan from its access token, and a plain plan without one", () => {
    const dir = mkdtempSync(join(tmpdir(), "posthog-tui-"));
    dirs.push(dir);
    const path = join(dir, "auth.json");
    expect(chatgptPlan(path)).toBe("ChatGPT plan");
    const access = jwt({
      "https://api.openai.com/auth": { chatgpt_plan_type: "plus" },
    });
    writeFileSync(
      path,
      JSON.stringify({ "openai-codex": { type: "oauth", access } }),
    );
    expect(chatgptPlan(path)).toBe("ChatGPT Plus");
  });
});
