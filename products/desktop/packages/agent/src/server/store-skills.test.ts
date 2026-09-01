import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { zipSync } from "fflate";
import { afterEach, describe, expect, it } from "vitest";
import {
  buildStoreSkillsInstructions,
  getStoreSkillRoots,
  installStoreSkillsArchive,
  removeStoreSkillStubs,
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

// Pin the Claude root under the temporary home so a developer's CLAUDE_CONFIG_DIR never leaks in.
function rootsFor(home: string): string[] {
  return getStoreSkillRoots({ home, claudeConfigDir: join(home, ".claude") });
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

async function writeSkill(
  root: string,
  name: string,
  skillMd: string,
): Promise<string> {
  const skillDir = join(root, name);
  await mkdir(skillDir, { recursive: true });
  await writeFile(join(skillDir, "SKILL.md"), skillMd);
  return skillDir;
}

describe("store skills", () => {
  it("unpacks every stub into every skill root", async () => {
    const home = await temporaryHome();
    const roots = rootsFor(home);

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
      removed: [],
      rejected: 0,
      errors: [],
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

  it("puts the Claude root under CLAUDE_CONFIG_DIR when it is set", () => {
    expect(
      getStoreSkillRoots({ home: "/home/u", claudeConfigDir: "/cfg/claude" }),
    ).toEqual(["/cfg/claude/skills", "/home/u/.agents/skills"]);
    expect(rootsFor("/home/u")).toEqual([
      "/home/u/.claude/skills",
      "/home/u/.agents/skills",
    ]);
  });

  it("never replaces a bundled skill with a stub of the same name, but refreshes its own stubs", async () => {
    const home = await temporaryHome();
    const [claudeRoot, agentsRoot] = rootsFor(home);
    const bundledSkill = await writeSkill(
      claudeRoot,
      "querying-posthog-data",
      "---\nname: querying-posthog-data\n---\nThe real skill.",
    );
    // A real skill whose body mentions the marker text is still a real skill.
    const mentionsStore = await writeSkill(
      claudeRoot,
      "release-notes",
      "---\nname: release-notes\n---\nStubs carry source: posthog-skills-store in their frontmatter.",
    );
    const staleStub = await writeSkill(
      agentsRoot,
      "release-notes",
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
      collisions: ["querying-posthog-data", "release-notes"],
      removed: [],
      rejected: 0,
      errors: [],
    });
    await expect(
      readFile(join(bundledSkill, "SKILL.md"), "utf-8"),
    ).resolves.toContain("The real skill.");
    await expect(
      readFile(join(mentionsStore, "SKILL.md"), "utf-8"),
    ).resolves.toContain("Stubs carry");
    await expect(
      readFile(join(agentsRoot, "querying-posthog-data", "SKILL.md"), "utf-8"),
    ).resolves.toContain("source: posthog-skills-store");
    await expect(
      readFile(join(staleStub, "SKILL.md"), "utf-8"),
    ).resolves.toContain("version: '3'");
  });

  it("removes stubs from an earlier install that the bundle no longer contains", async () => {
    const home = await temporaryHome();
    const roots = rootsFor(home);
    for (const root of roots) {
      await writeSkill(root, "lost-access", stubSkillMd("lost-access"));
      await writeSkill(
        root,
        "bundled-skill",
        "---\nname: bundled-skill\n---\nShipped by the image.",
      );
    }

    const result = await installStoreSkillsArchive(
      bundle({ "still-mine/SKILL.md": stubSkillMd("still-mine") }),
      roots,
    );

    expect(result.installed).toEqual(["still-mine"]);
    expect(result.removed).toEqual(["lost-access"]);
    for (const root of roots) {
      await expect(exists(join(root, "lost-access", "SKILL.md"))).resolves.toBe(
        false,
      );
      await expect(
        exists(join(root, "bundled-skill", "SKILL.md")),
      ).resolves.toBe(true);
    }
  });

  it("removes every stub when the store is off for the user, and leaves real skills", async () => {
    const home = await temporaryHome();
    const [claudeRoot, agentsRoot] = rootsFor(home);
    await writeSkill(claudeRoot, "gone", stubSkillMd("gone"));
    await writeSkill(
      claudeRoot,
      "bundled-skill",
      "---\nname: bundled-skill\n---\nShipped by the image.",
    );

    // The second root does not exist yet, which is the state of a fresh sandbox.
    const result = await removeStoreSkillStubs([claudeRoot, agentsRoot]);

    expect(result).toEqual({ removed: ["gone"], errors: [] });
    await expect(exists(join(claudeRoot, "gone", "SKILL.md"))).resolves.toBe(
      false,
    );
    await expect(
      exists(join(claudeRoot, "bundled-skill", "SKILL.md")),
    ).resolves.toBe(true);
  });

  it("still installs into a healthy root when another root cannot be written", async () => {
    const home = await temporaryHome();
    const [claudeRoot, agentsRoot] = rootsFor(home);
    // A file where the root directory should be makes every write there fail.
    await mkdir(join(claudeRoot, ".."), { recursive: true });
    await writeFile(claudeRoot, "not a directory");

    const result = await installStoreSkillsArchive(
      bundle({ "still-mine/SKILL.md": stubSkillMd("still-mine") }),
      [claudeRoot, agentsRoot],
    );

    expect(result.installed).toEqual(["still-mine"]);
    expect(result.errors.length).toBeGreaterThan(0);
    expect(new Set(result.errors.map((error) => error.root))).toEqual(
      new Set([claudeRoot]),
    );
    await expect(
      exists(join(agentsRoot, "still-mine", "SKILL.md")),
    ).resolves.toBe(true);
  });

  it.each([
    ["path traversal", { "../escape/SKILL.md": "x" }],
    ["absolute path", { "/etc/SKILL.md": "x" }],
    ["uppercase skill name", { "Bad-Name/SKILL.md": "x" }],
    ["nested traversal", { "ok-name/../../SKILL.md": "x" }],
    ["missing SKILL.md", { "ok-name/README.md": "x" }],
  ])("rejects an archive entry with %s", async (_label, entries) => {
    const home = await temporaryHome();
    const roots = rootsFor(home);

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
