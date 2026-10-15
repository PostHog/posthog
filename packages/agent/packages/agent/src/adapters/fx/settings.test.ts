import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { applyFxProviderSettings, writeFxProviderSettings } from "./settings";

const provider = { baseUrl: "http://127.0.0.1:1/v1", model: "gpt-6-sol" };

let dir: string | null = null;

afterEach(async () => {
  if (dir) await rm(dir, { recursive: true, force: true });
  dir = null;
});

describe("fx settings", () => {
  it.each([
    {
      name: "a global allow rule",
      existing: { permission: { bash: "allow" } },
      workspaces: undefined,
    },
    {
      name: "a workspace allow rule",
      existing: {
        workspaces: {
          "/repo": {
            permission: { bash: { "git *": "allow" } },
            additional_directories: ["/data"],
          },
        },
      },
      workspaces: { "/repo": { additional_directories: ["/data"] } },
    },
    {
      name: "global and workspace allow rules",
      existing: {
        permission: { bash: "allow" },
        workspaces: { "/repo": { permission: { edit: "allow" } } },
      },
      workspaces: { "/repo": {} },
    },
  ])(
    "drops $name so fx asks the server before every command",
    ({ existing, workspaces }) => {
      const settings = applyFxProviderSettings(existing, provider);

      expect(settings.permission).toBeUndefined();
      expect(settings.workspaces).toEqual(workspaces);
    },
  );

  it("creates the settings file when none exists", async () => {
    dir = await mkdtemp(join(tmpdir(), "fx-settings-"));
    const path = join(dir, ".fx", "settings.json");

    await writeFxProviderSettings(provider, path);

    expect(JSON.parse(await readFile(path, "utf8"))).toMatchObject({
      provider: "posthog",
      models: { posthog: "gpt-6-sol" },
    });
  });

  it.each([
    { name: "invalid JSON", content: "{ not json" },
    { name: "a JSON array", content: "[]" },
  ])("keeps a settings file holding $name", async ({ content }) => {
    dir = await mkdtemp(join(tmpdir(), "fx-settings-"));
    const path = join(dir, "settings.json");
    await writeFile(path, content);

    await expect(writeFxProviderSettings(provider, path)).rejects.toThrow();

    expect(await readFile(path, "utf8")).toBe(content);
  });
});
