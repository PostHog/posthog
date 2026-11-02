import { existsSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { connectCodexCloud } from "./codexCloud";

describe("connectCodexCloud", () => {
  const dirs: string[] = [];
  afterEach(() => {
    for (const dir of dirs.splice(0))
      rmSync(dir, { recursive: true, force: true });
  });

  it("logs in to a throwaway file, uploads its tokens, and deletes the file", async () => {
    const dir = mkdtempSync(join(tmpdir(), "posthog-tui-"));
    dirs.push(dir);
    const path = join(dir, "cloud-auth.json");
    const login = vi.fn(async (authPath: string) => {
      writeFileSync(
        authPath,
        JSON.stringify({
          "openai-codex": {
            type: "oauth",
            access: "access-1",
            refresh: "refresh-1",
            expires: 1,
          },
        }),
      );
    });
    const connect = vi.fn(async () => ({
      status: "connected" as const,
      email: "me@example.com",
      plan_type: "plus",
      connected_at: "2026-10-09T00:00:00Z",
    }));
    const result = await connectCodexCloud({ login, connect, path });
    expect(login).toHaveBeenCalledWith(path);
    expect(connect).toHaveBeenCalledWith({
      access_token: "access-1",
      refresh_token: "refresh-1",
    });
    expect(result.email).toBe("me@example.com");
    expect(existsSync(path)).toBe(false);
  });

  it("deletes the file when the upload fails, so a stale login never lingers", async () => {
    const dir = mkdtempSync(join(tmpdir(), "posthog-tui-"));
    dirs.push(dir);
    const path = join(dir, "cloud-auth.json");
    const login = async (authPath: string): Promise<void> => {
      writeFileSync(
        authPath,
        JSON.stringify({
          "openai-codex": { type: "oauth", access: "a", refresh: "r" },
        }),
      );
    };
    const connect = async (): Promise<never> => {
      throw new Error("nope");
    };
    await expect(connectCodexCloud({ login, connect, path })).rejects.toThrow(
      "nope",
    );
    expect(existsSync(path)).toBe(false);
  });
});
