import { mkdtempSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { OAuthCredentials } from "@earendil-works/pi-ai";
import {
  loginPosthog,
  refreshPosthog,
} from "@posthog/harness/extensions/posthog-provider/oauth";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TuiAuth } from "./auth";

vi.mock("@posthog/harness/extensions/posthog-provider/oauth", () => ({
  loginPosthog: vi.fn(),
  refreshPosthog: vi.fn(),
}));

const credentials = (access: string, expires: number): OAuthCredentials => ({
  access,
  refresh: `${access}-refresh`,
  expires,
  region: "us",
});

describe("TuiAuth", () => {
  let path: string;

  beforeEach(() => {
    vi.resetAllMocks();
    path = join(mkdtempSync(join(tmpdir(), "tui-auth-")), "auth.json");
  });

  it("has no session before sign-in", () => {
    expect(TuiAuth.load(path)).toBeNull();
  });

  it("keeps the session from sign-in in a private file", async () => {
    vi.mocked(loginPosthog).mockResolvedValue(
      credentials("first", Date.now() + 60_000),
    );
    await TuiAuth.login("us", { onAuth: () => {} }, path);

    expect(statSync(path).mode & 0o777).toBe(0o600);
    expect(await TuiAuth.load(path)?.getAccessToken()).toBe("first");
    expect(TuiAuth.load(path)?.apiHost).toBe("https://us.posthog.com");
  });

  it("refreshes an expired token once for concurrent callers and keeps the new one", async () => {
    vi.mocked(loginPosthog).mockResolvedValue(
      credentials("old", Date.now() - 1),
    );
    vi.mocked(refreshPosthog).mockResolvedValue(
      credentials("new", Date.now() + 60_000),
    );
    const auth = await TuiAuth.login("us", { onAuth: () => {} }, path);

    const tokens = await Promise.all([
      auth.getAccessToken(),
      auth.getAccessToken(),
    ]);

    expect(tokens).toEqual(["new", "new"]);
    expect(refreshPosthog).toHaveBeenCalledTimes(1);
    expect(await TuiAuth.load(path)?.getAccessToken()).toBe("new");
  });
});
