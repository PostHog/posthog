import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { zipSync } from "fflate";
import { afterEach, describe, expect, it } from "vitest";
import {
  buildStoreSkillsInstructions,
  getStoreSkillRoots,
  installStoreSkillsArchive,
} from "./store-skills";

const directories: string[] = [];

afterEach(async () => {
  await Promise.all(
    directories
      .splice(0)
      .map((directory) => rm(directory, { recursive: true, force: true })),
  );
});

async function temporaryHome(): Promise<string> {
  const directory = await mkdtemp(join(tmpdir(), "store-skills-"));
  directories.push(directory);
  return directory;
}

function stubSkillMd(name: string): string {
  return [
    "---",
    `name: ${name}`,
    `description: ${name} description`,
    "metadata:",
    "  version: '3'",
    "  source: posthog-skills-store",
    "---",
    "",
    `Run skill-get for ${name}.`,
  ].join("\n");
}

function bundle(entries: Record<string, string>): Uint8Array {
  const encoder = new TextEncoder();
  return zipSync(
    Object.fromEntries(
      Object.entries(entries).map(([path, content]) => [
        path,
        encoder.encode(content),
      ]),
    ),
  );
}

const exists = (path: string): Promise<boolean> =>
  readFile(path, "utf-8").then(
    () => true,
    () => false,
  );

describe("store skills", () => {
  it("unpacks every stub into every skill root", async () => {
    const home = await temporaryHome();
    const roots = getStoreSkillRoots(home);

    const result = await installStoreSkillsArchive(
      bundle({
        "tam-quota-forecast/SKILL.md": stubSkillMd("tam-quota-forecast"),
        "release-notes/SKILL.md": stubSkillMd("release-notes"),
      }),
      roots,
    );

    expect(result).toEqual({
      installed: ["tam-quota-forecast", "release-notes"],
      collisions: [],
      rejected: 0,
    });
    for (const root of roots) {
      await expect(
        readFile(join(root, "tam-quota-forecast", "SKILL.md"), "utf-8"),
      ).resolves.toContain("name: tam-quota-forecast");
      await expect(
        exists(join(root, "release-notes", "SKILL.md")),
      ).resolves.toBe(true);
    }
  });

  it("never replaces a bundled skill with a stub of the same name, but refreshes its own stubs", async () => {
    const home = await temporaryHome();
    const [claudeRoot, agentsRoot] = getStoreSkillRoots(home);
    const bundledSkill = join(claudeRoot, "querying-posthog-data");
    await mkdir(bundledSkill, { recursive: true });
    await writeFile(
      join(bundledSkill, "SKILL.md"),
      "---\nname: querying-posthog-data\n---\nThe real skill.",
    );
    const staleStub = join(agentsRoot, "release-notes");
    await mkdir(staleStub, { recursive: true });
    await writeFile(
      join(staleStub, "SKILL.md"),
      stubSkillMd("release-notes").replace("version: '3'", "version: '1'"),
    );

    const result = await installStoreSkillsArchive(
      bundle({
        "querying-posthog-data/SKILL.md": stubSkillMd("querying-posthog-data"),
        "release-notes/SKILL.md": stubSkillMd("release-notes"),
      }),
      [claudeRoot, agentsRoot],
    );

    expect(result).toEqual({
      installed: ["querying-posthog-data", "release-notes"],
      collisions: ["querying-posthog-data"],
      rejected: 0,
    });
    await expect(
      readFile(join(bundledSkill, "SKILL.md"), "utf-8"),
    ).resolves.toContain("The real skill.");
    await expect(
      readFile(join(agentsRoot, "querying-posthog-data", "SKILL.md"), "utf-8"),
    ).resolves.toContain("source: posthog-skills-store");
    await expect(
      readFile(join(staleStub, "SKILL.md"), "utf-8"),
    ).resolves.toContain("version: '3'");
  });

  it.each([
    ["path traversal", { "../escape/SKILL.md": "x" }],
    ["absolute path", { "/etc/SKILL.md": "x" }],
    ["uppercase skill name", { "Bad-Name/SKILL.md": "x" }],
    ["nested traversal", { "ok-name/../../SKILL.md": "x" }],
    ["missing SKILL.md", { "ok-name/README.md": "x" }],
  ])("rejects an archive entry with %s", async (_label, entries) => {
    const home = await temporaryHome();
    const roots = getStoreSkillRoots(home);

    const result = await installStoreSkillsArchive(bundle(entries), roots);

    expect(result.installed).toEqual([]);
    expect(result.rejected).toBeGreaterThan(0);
    await expect(exists(join(home, "escape", "SKILL.md"))).resolves.toBe(false);
    await expect(exists(join(home, "SKILL.md"))).resolves.toBe(false);
  });

  it("adds a prompt section only when a stub was installed", () => {
    expect(buildStoreSkillsInstructions(0)).toBe("");
    expect(buildStoreSkillsInstructions(3)).toContain("skill-get");
  });
});
