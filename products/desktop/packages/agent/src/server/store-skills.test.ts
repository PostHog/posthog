import {
  mkdir,
  mkdtemp,
  readdir,
  readFile,
  rm,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { StoreSkillStub } from "@posthog/shared";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  buildStoreSkillsInstructions,
  getStoreSkillRoots,
  hasStoreMarker,
  installStoreSkillStubs,
  listStoreSkillStubs,
  removeStoreSkillStubs,
  renderStoreSkillStub,
  syncStoreSkills,
} from "./store-skills";

// Path prefixes whose removal or write must fail, to stand in for a busy directory or a full disk.
const failingRemovals = new Set<string>();
const failingWrites = new Set<string>();

vi.mock("node:fs/promises", async (importOriginal) => {
  const actual = await importOriginal<typeof import("node:fs/promises")>();
  const failFor = (prefixes: Set<string>, path: unknown): boolean =>
    [...prefixes].some((prefix) => String(path).startsWith(prefix));
  return {
    ...actual,
    rm: (
      path: Parameters<typeof actual.rm>[0],
      options?: Parameters<typeof actual.rm>[1],
    ) =>
      failFor(failingRemovals, path)
        ? Promise.reject(new Error(`EBUSY: ${String(path)}`))
        : actual.rm(path, options),
    writeFile: (
      path: Parameters<typeof actual.writeFile>[0],
      data: Parameters<typeof actual.writeFile>[1],
      options?: Parameters<typeof actual.writeFile>[2],
    ) =>
      failFor(failingWrites, path)
        ? Promise.reject(new Error(`ENOSPC: ${String(path)}`))
        : actual.writeFile(path, data, options),
  };
});

const directories: string[] = [];

afterEach(async () => {
  vi.unstubAllEnvs();
  failingRemovals.clear();
  failingWrites.clear();
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
    // So is one whose frontmatter has the marker line indented under another key.
    const describesStore = await writeSkill(
      claudeRoot,
      "store-guide",
      "---\nname: store-guide\ndescription: |\n  Explains stubs whose frontmatter reads\n  source: posthog-skills-store\n---\nThe real skill.",
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
        stub("store-guide"),
      ],
      [claudeRoot, agentsRoot],
    );

    expect(result).toEqual({
      installed: [
        "querying-posthog-data",
        "release-notes",
        "half-written",
        "store-guide",
      ],
      collisions: [
        "querying-posthog-data",
        "release-notes",
        "half-written",
        "store-guide",
      ],
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
      readFile(join(describesStore, "SKILL.md"), "utf-8"),
    ).resolves.toContain("The real skill.");
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

  it.each([
    ["the stub the agent renders", renderStoreSkillStub(stub("a")), true],
    [
      "the stub the bundle endpoint renders",
      "---\nname: a\ndescription: A skill.\nmetadata:\n  version: '3'\n  source: posthog-skills-store\n---\n\nBody.",
      true,
    ],
    [
      "a quoted source value",
      "---\nname: a\nmetadata:\n  source: 'posthog-skills-store'\n---\nBody.",
      true,
    ],
    [
      "the marker line inside a block-scalar description",
      "---\nname: a\ndescription: |\n  Stubs read\n  source: posthog-skills-store\nmetadata:\n  version: '1'\n---\nBody.",
      false,
    ],
    [
      "the marker nested below metadata",
      "---\nname: a\nmetadata:\n  origin:\n    source: posthog-skills-store\n---\nBody.",
      false,
    ],
    [
      "a top-level source key",
      "---\nname: a\nsource: posthog-skills-store\n---\nBody.",
      false,
    ],
    ["no frontmatter", "source: posthog-skills-store\n", false],
  ])("reads the store marker from %s", (_label, skillMd, expected) => {
    expect(hasStoreMarker(skillMd)).toBe(expected);
  });

  it("keeps the previous stub when writing the replacement fails", async () => {
    const home = await temporaryHome();
    const [claudeRoot] = rootsFor(home);
    const previous = await writeSkill(
      claudeRoot,
      "flaky",
      renderStoreSkillStub(stub("flaky", 1)),
    );
    failingWrites.add(join(claudeRoot, ".flaky.store-stub-"));

    const result = await installStoreSkillStubs(
      [stub("flaky", 2)],
      [claudeRoot],
    );

    expect(result.installed).toEqual([]);
    expect(result.errors).toEqual([
      {
        root: claudeRoot,
        skillName: "flaky",
        message: expect.stringContaining("ENOSPC"),
      },
    ]);
    await expect(
      readFile(join(previous, "SKILL.md"), "utf-8"),
    ).resolves.toContain("version: '1'");
    // No staging directory is left behind for the harness to list.
    await expect(readdir(claudeRoot)).resolves.toEqual(["flaky"]);
    failingWrites.clear();
    // The next session repairs it.
    await expect(
      installStoreSkillStubs([stub("flaky", 2)], [claudeRoot]),
    ).resolves.toMatchObject({ installed: ["flaky"], errors: [] });
  });

  it("keeps pruning stale stubs after one cannot be removed", async () => {
    const home = await temporaryHome();
    const [claudeRoot] = rootsFor(home);
    for (const name of ["busy", "stale"]) {
      await writeSkill(claudeRoot, name, renderStoreSkillStub(stub(name)));
    }
    failingRemovals.add(join(claudeRoot, "busy"));

    const result = await removeStoreSkillStubs([claudeRoot]);

    expect(result.removed).toEqual(["stale"]);
    expect(result.errors).toEqual([
      {
        root: claudeRoot,
        skillName: "busy",
        message: expect.stringContaining("EBUSY"),
      },
    ]);
    await expect(exists(join(claudeRoot, "stale", "SKILL.md"))).resolves.toBe(
      false,
    );
  });

  it("counts what the harness will list: installed stubs, or the kept ones without run context", async () => {
    const home = await temporaryHome();
    const roots = rootsFor(home);
    const logger = { info: vi.fn(), warn: vi.fn() };
    const context = { taskId: "task", runId: "run" };

    await expect(
      syncStoreSkills(
        { store_skills: [stub("one"), stub("two")] },
        context,
        logger,
        roots,
      ),
    ).resolves.toBe(2);
    await expect(syncStoreSkills(null, context, logger, roots)).resolves.toBe(
      2,
    );
    await expect(syncStoreSkills({}, context, logger, roots)).resolves.toBe(0);
    await expect(exists(join(roots[0], "one", "SKILL.md"))).resolves.toBe(
      false,
    );
  });

  it("adds a prompt section only when a stub was installed", () => {
    expect(buildStoreSkillsInstructions(0)).toBe("");
    expect(buildStoreSkillsInstructions(3)).toContain("skill-get");
  });
});
