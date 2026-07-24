import { existsSync } from "node:fs";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createHarnessRuntime } from "./runtime";

const temporaryDirectories: string[] = [];

async function temporaryDirectory(): Promise<string> {
  const directory = await mkdtemp(join(tmpdir(), "posthog-harness-"));
  temporaryDirectories.push(directory);
  return directory;
}

afterEach(async () => {
  vi.unstubAllEnvs();
  await Promise.all(
    temporaryDirectories
      .splice(0)
      .map((directory) => rm(directory, { force: true, recursive: true })),
  );
});

describe("createHarnessRuntime", () => {
  it(
    "returns a native Pi runtime with the PostHog model and named harness extensions",
    { timeout: 15_000 },
    async () => {
      vi.stubEnv("PI_OFFLINE", "1");
      const pi = await import("@earendil-works/pi-coding-agent");
      const cwd = await temporaryDirectory();
      const agentDir = await temporaryDirectory();

      const runtime = await createHarnessRuntime({
        agentDir,
        authStorage: pi.AuthStorage.inMemory(),
        cwd,
        sessionManager: pi.SessionManager.inMemory(cwd),
      });

      try {
        expect(runtime).toBeInstanceOf(pi.AgentSessionRuntime);
        expect(runtime.session.model?.provider).toBe("posthog");
        expect(runtime.services.settingsManager.isProjectTrusted()).toBe(false);
        expect(
          runtime.services.resourceLoader
            .getExtensions()
            .extensions.map((extension) => extension.path),
        ).toEqual(
          expect.arrayContaining([
            "<inline:hog-branding>",
            "<inline:posthog-provider>",
            "<inline:web-access>",
            "<inline:subagent>",
            "<inline:workflow>",
            "<inline:mcp>",
          ]),
        );
      } finally {
        await runtime.dispose();
      }
    },
  );

  it("keeps desktop-provided OAuth credentials in memory without touching auth.json", async () => {
    vi.stubEnv("PI_OFFLINE", "1");
    const pi = await import("@earendil-works/pi-coding-agent");
    const cwd = await temporaryDirectory();
    const agentDir = await temporaryDirectory();

    const runtime = await createHarnessRuntime({
      agentDir,
      cwd,
      posthogOAuthCredentials: {
        access: "access-token",
        refresh: "refresh-token",
        expires: Date.now() + 60_000,
        region: "us",
      },
      sessionManager: pi.SessionManager.inMemory(cwd),
    });

    try {
      expect(runtime.services.authStorage.get("posthog")).toMatchObject({
        type: "oauth",
        access: "access-token",
        refresh: "refresh-token",
      });
      expect(existsSync(join(agentDir, "auth.json"))).toBe(false);
    } finally {
      await runtime.dispose();
    }
  });

  it("seeds the in-memory store from auth.json without writing back to it", async () => {
    vi.stubEnv("PI_OFFLINE", "1");
    const pi = await import("@earendil-works/pi-coding-agent");
    const cwd = await temporaryDirectory();
    const agentDir = await temporaryDirectory();
    const authPath = join(agentDir, "auth.json");
    const storedCredentials = {
      anthropic: { type: "api_key", key: "anthropic-key" },
      posthog: {
        type: "oauth",
        access: "stale-access",
        refresh: "stale-refresh",
        expires: 0,
      },
    };
    await writeFile(authPath, JSON.stringify(storedCredentials));

    const runtime = await createHarnessRuntime({
      agentDir,
      cwd,
      posthogOAuthCredentials: {
        access: "access-token",
        refresh: "refresh-token",
        expires: Date.now() + 60_000,
        region: "us",
      },
      sessionManager: pi.SessionManager.inMemory(cwd),
    });

    try {
      expect(runtime.services.authStorage.get("anthropic")).toMatchObject({
        type: "api_key",
        key: "anthropic-key",
      });
      expect(runtime.services.authStorage.get("posthog")).toMatchObject({
        access: "access-token",
        refresh: "refresh-token",
      });
      expect(JSON.parse(await readFile(authPath, "utf8"))).toEqual(
        storedCredentials,
      );
    } finally {
      await runtime.dispose();
    }
  });

  it("uses a static provider key ahead of stored OAuth credentials", async () => {
    vi.stubEnv("PI_OFFLINE", "1");
    const pi = await import("@earendil-works/pi-coding-agent");
    const cwd = await temporaryDirectory();
    const agentDir = await temporaryDirectory();
    await writeFile(
      join(agentDir, "auth.json"),
      JSON.stringify({
        posthog: {
          type: "oauth",
          access: "stale-access",
          refresh: "stale-refresh",
          expires: 0,
        },
      }),
    );

    const runtime = await createHarnessRuntime({
      agentDir,
      cwd,
      apiKey: "proxy-key",
      baseUrl: "http://127.0.0.1:1234",
      sessionManager: pi.SessionManager.inMemory(cwd),
    });

    try {
      await expect(
        runtime.services.modelRegistry.getApiKeyForProvider("posthog"),
      ).resolves.toBe("proxy-key");
    } finally {
      await runtime.dispose();
    }
  });

  it("uses file-backed auth storage when no desktop credentials are provided", async () => {
    vi.stubEnv("PI_OFFLINE", "1");
    const pi = await import("@earendil-works/pi-coding-agent");
    const cwd = await temporaryDirectory();
    const agentDir = await temporaryDirectory();

    const runtime = await createHarnessRuntime({
      agentDir,
      cwd,
      sessionManager: pi.SessionManager.inMemory(cwd),
    });

    try {
      runtime.services.authStorage.set("posthog", {
        type: "oauth",
        access: "access-token",
        refresh: "refresh-token",
        expires: Date.now() + 60_000,
      });

      expect(existsSync(join(agentDir, "auth.json"))).toBe(true);
    } finally {
      await runtime.dispose();
    }
  });
});
