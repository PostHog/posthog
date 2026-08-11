import { existsSync } from "node:fs";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { InMemoryCredentialStore } from "@earendil-works/pi-ai";
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
        credentialStore: new InMemoryCredentialStore(),
        cwd,
        sessionManager: pi.SessionManager.inMemory(cwd),
      });

      try {
        expect(runtime).toBeInstanceOf(pi.AgentSessionRuntime);
        expect(runtime.session.model?.provider).toBe("posthog");
        expect(runtime.session.getAvailableThinkingLevels()).toContain("off");
        expect(runtime.services.settingsManager.isProjectTrusted()).toBe(false);
        const extensionPaths = runtime.services.resourceLoader
          .getExtensions()
          .extensions.map((extension) => extension.path);
        expect(extensionPaths).toEqual(
          expect.arrayContaining([
            "<inline:hog-branding>",
            "<inline:posthog-provider>",
            "<inline:web-access>",
            "<inline:mcp>",
          ]),
        );
        expect(extensionPaths).not.toEqual(
          expect.arrayContaining([
            "<inline:background-jobs>",
            "<inline:subagent>",
            "<inline:workflow>",
          ]),
        );
      } finally {
        await runtime.dispose();
      }
    },
  );

  it.each([
    { label: "false", projectTrusted: () => false, loaded: false },
    { label: "true", projectTrusted: () => true, loaded: true },
  ])(
    "loads project-local extensions when project trust is $label",
    async ({ projectTrusted, loaded }) => {
      vi.stubEnv("PI_OFFLINE", "1");
      const pi = await import("@earendil-works/pi-coding-agent");
      const cwd = await temporaryDirectory();
      const agentDir = await temporaryDirectory();
      const extensionPath = join(cwd, ".pi", "extensions", "project.ts");
      await mkdir(join(cwd, ".pi", "extensions"), { recursive: true });
      await writeFile(
        extensionPath,
        "export default function projectExtension() {}\n",
      );

      const runtime = await createHarnessRuntime({
        agentDir,
        credentialStore: new InMemoryCredentialStore(),
        cwd,
        projectTrusted,
        sessionManager: pi.SessionManager.inMemory(cwd),
      });

      try {
        const extensionPaths = runtime.services.resourceLoader
          .getExtensions()
          .extensions.map((extension) => extension.path);
        expect(extensionPaths.includes(extensionPath)).toBe(loaded);
      } finally {
        await runtime.dispose();
      }
    },
  );

  it("restores the session model before calculating context usage", async () => {
    vi.stubEnv("PI_OFFLINE", "1");
    const pi = await import("@earendil-works/pi-coding-agent");
    const cwd = await temporaryDirectory();
    const agentDir = await temporaryDirectory();
    const sessionManager = pi.SessionManager.inMemory(cwd);
    sessionManager.appendModelChange("posthog", "claude-haiku-4-5");
    sessionManager.appendMessage({
      role: "user",
      content: "continue",
      timestamp: Date.now(),
    });

    const runtime = await createHarnessRuntime({
      agentDir,
      apiKey: "proxy-key",
      cwd,
      sessionManager,
    });

    try {
      expect(runtime.session.model?.id).toBe("claude-haiku-4-5");
      expect(runtime.session.getSessionStats().contextUsage).toMatchObject({
        contextWindow: 200_000,
      });
    } finally {
      await runtime.dispose();
    }
  });

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
        expires: Date.now() + 10 * 60_000,
        region: "us",
      },
      sessionManager: pi.SessionManager.inMemory(cwd),
    });

    try {
      await expect(
        runtime.services.modelRuntime.getAuth("posthog"),
      ).resolves.toMatchObject({ auth: { apiKey: "access-token" } });
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
        expires: Date.now() + 10 * 60_000,
        region: "us",
      },
      sessionManager: pi.SessionManager.inMemory(cwd),
    });

    try {
      await expect(
        runtime.services.modelRuntime.getAuth("anthropic"),
      ).resolves.toMatchObject({ auth: { apiKey: "anthropic-key" } });
      await expect(
        runtime.services.modelRuntime.getAuth("posthog"),
      ).resolves.toMatchObject({ auth: { apiKey: "access-token" } });
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
        runtime.services.modelRuntime.getAuth("posthog"),
      ).resolves.toMatchObject({ auth: { apiKey: "proxy-key" } });
    } finally {
      await runtime.dispose();
    }
  });

  it("uses file-backed credentials when desktop credentials are absent", async () => {
    vi.stubEnv("PI_OFFLINE", "1");
    const pi = await import("@earendil-works/pi-coding-agent");
    const cwd = await temporaryDirectory();
    const agentDir = await temporaryDirectory();
    const authPath = join(agentDir, "auth.json");
    await writeFile(
      authPath,
      JSON.stringify({ posthog: { type: "api_key", key: "stored-key" } }),
    );

    const runtime = await createHarnessRuntime({
      agentDir,
      cwd,
      sessionManager: pi.SessionManager.inMemory(cwd),
    });

    try {
      await expect(
        runtime.services.modelRuntime.listCredentials(),
      ).resolves.toContainEqual({ providerId: "posthog", type: "api_key" });
    } finally {
      await runtime.dispose();
    }
  });
});
