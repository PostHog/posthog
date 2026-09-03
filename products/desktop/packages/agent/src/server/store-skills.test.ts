import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { StoreSkillStub } from "@posthog/shared";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  buildStoreSkillsInstructions,
  getStoreSkillRoots,
  installStoreSkillStubs,
  listStoreSkillStubs,
  removeStoreSkillStubs,
  renderStoreSkillStub,
} from "./store-skills";

const directories: string[] = [];

afterEach(async () => {
  vi.unstubAllEnvs();
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

function stub(name: string, version = 3): StoreSkillStub {
  return { name, description: `${name} description`, version };
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
  it("renders a pointer SKILL.md the store marker and the fetch contract can be read from", () => {
    const skillMd = renderStoreSkillStub({
      name: "tam-quota-forecast",
      description: 'Forecast "quota" usage.\nSecond line.',
      version: 7,
    });

    expect(skillMd).toContain("name: tam-quota-forecast");
    expect(skillMd).toContain(
      'description: "Forecast \\"quota\\" usage.\\nSecond line."',
    );
    expect(skillMd).toContain("  version: '7'");
    expect(skillMd).toContain("  source: posthog-skills-store");
    expect(skillMd).toContain(
      'call skill-get {"skill_name": "tam-quota-forecast"}',
    );
    expect(skillMd).toContain("body_next_offset");
    expect(skillMd).toContain('"version": <version>');
  });

  it("writes every stub into every skill root", async () => {
    const home = await temporaryHome();
    const roots = rootsFor(home);

    const result = await installStoreSkillStubs(
      [stub("tam-quota-forecast"), stub("release-notes")],
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

  it.each([
    ["set", "/cfg/claude", "/cfg/claude/skills"],
    [
      "empty, which the Claude adapter treats as unset",
      "",
      "/home/u/.claude/skills",
    ],
  ])(
    "reads CLAUDE_CONFIG_DIR from the environment when %s",
    (_label, value, claudeRoot) => {
      vi.stubEnv("CLAUDE_CONFIG_DIR", value);

      expect(getStoreSkillRoots({ home: "/home/u" })[0]).toBe(claudeRoot);
    },
  );

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
      renderStoreSkillStub(stub("release-notes", 1)),
    );
    // A directory with no SKILL.md yet is somebody's work in progress, not an empty slot.
    const inProgress = join(agentsRoot, "half-written");
    await mkdir(inProgress, { recursive: true });
    await writeFile(join(inProgress, "notes.md"), "draft");

    const result = await installStoreSkillStubs(
      [
        stub("querying-posthog-data"),
        stub("release-notes"),
        stub("half-written"),
      ],
      [claudeRoot, agentsRoot],
    );

    expect(result).toEqual({
      installed: ["querying-posthog-data", "release-notes", "half-written"],
      collisions: ["querying-posthog-data", "release-notes", "half-written"],
      removed: [],
      rejected: 0,
      errors: [],
    });
    await expect(readFile(join(inProgress, "notes.md"), "utf-8")).resolves.toBe(
      "draft",
    );
    await expect(exists(join(inProgress, "SKILL.md"))).resolves.toBe(false);
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

  it("removes stubs from an earlier install that the run no longer lists", async () => {
    const home = await temporaryHome();
    const roots = rootsFor(home);
    for (const root of roots) {
      await writeSkill(
        root,
        "lost-access",
        renderStoreSkillStub(stub("lost-access")),
      );
      await writeSkill(
        root,
        "bundled-skill",
        "---\nname: bundled-skill\n---\nShipped by the image.",
      );
    }

    const result = await installStoreSkillStubs([stub("still-mine")], roots);

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

  it("lists the stubs on disk so a session that keeps them still gets the pointer guidance", async () => {
    const home = await temporaryHome();
    const [claudeRoot, agentsRoot] = rootsFor(home);
    await writeSkill(
      claudeRoot,
      "kept-stub",
      renderStoreSkillStub(stub("kept-stub")),
    );
    await writeSkill(
      agentsRoot,
      "kept-stub",
      renderStoreSkillStub(stub("kept-stub")),
    );
    await writeSkill(
      agentsRoot,
      "other-stub",
      renderStoreSkillStub(stub("other-stub")),
    );
    await writeSkill(
      claudeRoot,
      "bundled-skill",
      "---\nname: bundled-skill\n---\nShipped by the image.",
    );

    await expect(
      listStoreSkillStubs([claudeRoot, agentsRoot]),
    ).resolves.toEqual(["kept-stub", "other-stub"]);
  });

  it("removes every stub when the run lists none, and leaves real skills", async () => {
    const home = await temporaryHome();
    const [claudeRoot, agentsRoot] = rootsFor(home);
    await writeSkill(claudeRoot, "gone", renderStoreSkillStub(stub("gone")));
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

    const result = await installStoreSkillStubs(
      [stub("still-mine")],
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
    ["path traversal in the name", { ...stub("ok"), name: "../escape" }],
    ["an uppercase name", { ...stub("ok"), name: "Bad-Name" }],
    ["a double hyphen", { ...stub("ok"), name: "bad--name" }],
    ["an empty description", { ...stub("ok"), description: "  " }],
    ["a fractional version", { ...stub("ok"), version: 1.5 }],
  ])("rejects a stub with %s", async (_label, badStub) => {
    const home = await temporaryHome();
    const roots = rootsFor(home);

    const result = await installStoreSkillStubs([badStub], roots);

    expect(result.installed).toEqual([]);
    expect(result.rejected).toBe(1);
    await expect(exists(join(home, "escape", "SKILL.md"))).resolves.toBe(false);
  });

  it("adds a prompt section only when a stub was installed", () => {
    expect(buildStoreSkillsInstructions(0)).toBe("");
    expect(buildStoreSkillsInstructions(3)).toContain("skill-get");
  });
});
