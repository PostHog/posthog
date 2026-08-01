import type {
  LlmSkillListItem,
  PostHogAPIClient,
} from "@posthog/api-client/posthog-client";
import { describe, expect, it, vi } from "vitest";
import type { SkillsWorkspaceClient } from "./teamSkillsService";
import {
  markInstalledTeamSkills,
  TeamSkillsService,
} from "./teamSkillsService";

function makeService(
  workspace: Partial<SkillsWorkspaceClient> = {},
): TeamSkillsService {
  return new TeamSkillsService(workspace as SkillsWorkspaceClient);
}

function makeItem(overrides: Partial<LlmSkillListItem>): LlmSkillListItem {
  return {
    id: "skill-1",
    name: "pr-shepherd",
    description: "Shepherds PRs",
    allowed_tools: [],
    metadata: {},
    version: 2,
    is_latest: true,
    latest_version: 2,
    created_by: { email: "dev@posthog.com" },
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-02-01T00:00:00Z",
    ...overrides,
  };
}

function makeClient(result: LlmSkillListItem[] | null): PostHogAPIClient {
  return {
    listLlmSkills: vi
      .fn<PostHogAPIClient["listLlmSkills"]>()
      .mockResolvedValue(result),
  } satisfies Partial<PostHogAPIClient> as unknown as PostHogAPIClient;
}

describe("TeamSkillsService.listTeamSkills", () => {
  it("reports the feature as unavailable when the API returns null", async () => {
    const listing = await makeService().listTeamSkills(makeClient(null));

    expect(listing).toEqual({ available: false, skills: [] });
  });

  it("maps team skills", async () => {
    const client = makeClient([
      makeItem({}),
      makeItem({ id: "skill-2", name: "release-notes", created_by: null }),
    ]);

    const listing = await makeService().listTeamSkills(client);

    expect(listing.available).toBe(true);
    expect(listing.skills).toEqual([
      {
        id: "skill-1",
        name: "pr-shepherd",
        description: "Shepherds PRs",
        version: 2,
        updatedAt: "2026-02-01T00:00:00Z",
        createdByEmail: "dev@posthog.com",
        installedLocally: false,
      },
      expect.objectContaining({ name: "release-notes", createdByEmail: null }),
    ]);
  });

  it("drops non-latest versions", async () => {
    const client = makeClient([
      makeItem({ is_latest: false, version: 1 }),
      makeItem({ id: "skill-1b", version: 2 }),
    ]);

    const listing = await makeService().listTeamSkills(client);

    expect(listing.skills).toHaveLength(1);
    expect(listing.skills[0]?.id).toBe("skill-1b");
  });
});

describe("markInstalledTeamSkills", () => {
  it("marks team skills that exist locally by name", async () => {
    const listing = await makeService().listTeamSkills(
      makeClient([
        makeItem({}),
        makeItem({ id: "skill-2", name: "release-notes" }),
      ]),
    );

    const marked = markInstalledTeamSkills(listing, [
      "release-notes",
      "unrelated-local",
    ]);

    expect(marked.skills.map((s) => [s.name, s.installedLocally])).toEqual([
      ["pr-shepherd", false],
      ["release-notes", true],
    ]);
  });
});

describe("TeamSkillsService.publishSkill", () => {
  const exported = {
    name: "pr-shepherd",
    description: "Shepherds PRs",
    body: "# Body",
    files: [{ path: "references/guide.md", content: "guide" }],
  };

  it("creates a new skill on first publish", async () => {
    const createLlmSkill = vi.fn().mockResolvedValue(makeItem({ version: 1 }));
    const client = {
      listLlmSkills: vi.fn().mockResolvedValue([]),
      createLlmSkill,
    } as unknown as PostHogAPIClient;

    const result = await makeService().publishSkill(client, exported);

    expect(createLlmSkill).toHaveBeenCalledWith({
      name: "pr-shepherd",
      description: "Shepherds PRs",
      body: "# Body",
      files: exported.files,
    });
    expect(result).toEqual({ version: 1 });
  });

  it("publishes a new version against the current latest", async () => {
    const publishLlmSkillVersion = vi
      .fn()
      .mockResolvedValue(makeItem({ version: 3 }));
    const client = {
      listLlmSkills: vi
        .fn()
        .mockResolvedValue([makeItem({ version: 2, latest_version: 2 })]),
      publishLlmSkillVersion,
    } as unknown as PostHogAPIClient;

    const result = await makeService().publishSkill(client, exported);

    expect(publishLlmSkillVersion).toHaveBeenCalledWith("pr-shepherd", {
      body: "# Body",
      description: "Shepherds PRs",
      files: exported.files,
      base_version: 2,
    });
    expect(result).toEqual({ version: 3 });
  });

  it("rejects publishing without a description", async () => {
    await expect(
      makeService().publishSkill(makeClient([]), {
        ...exported,
        description: "  ",
      }),
    ).rejects.toThrow("Add a description");
  });

  it("rejects publishing when the feature is unavailable", async () => {
    await expect(
      makeService().publishSkill(makeClient(null), exported),
    ).rejects.toThrow("not enabled");
  });
});

describe("TeamSkillsService.fetchSkillForInstall", () => {
  it("fetches the body plus every companion file", async () => {
    const client = {
      getLlmSkillByName: vi.fn().mockResolvedValue({
        name: "pr-shepherd",
        description: "Shepherds PRs",
        body: "# Body",
        files: [
          { path: "references/guide.md", content_type: "text/plain" },
          { path: "scripts/run.sh", content_type: "text/plain" },
        ],
      }),
      getLlmSkillFile: vi
        .fn()
        .mockImplementation(async (_name: string, path: string) => ({
          path,
          content: `content of ${path}`,
          content_type: "text/plain",
        })),
    } as unknown as PostHogAPIClient;

    const skill = await makeService().fetchSkillForInstall(
      client,
      "pr-shepherd",
    );

    expect(skill).toEqual({
      name: "pr-shepherd",
      description: "Shepherds PRs",
      body: "# Body",
      files: [
        {
          path: "references/guide.md",
          content: "content of references/guide.md",
        },
        { path: "scripts/run.sh", content: "content of scripts/run.sh" },
      ],
    });
  });
});

describe("TeamSkillsService.publishLocalSkill", () => {
  it("exports from disk, publishes, and reports skipped files", async () => {
    const exportSkill = vi.fn().mockResolvedValue({
      name: "pr-shepherd",
      description: "Shepherds PRs",
      body: "# Body",
      files: [],
      skipped: ["assets/logo.png"],
    });
    const createLlmSkill = vi.fn().mockResolvedValue(makeItem({ version: 1 }));
    const client = {
      listLlmSkills: vi.fn().mockResolvedValue([]),
      createLlmSkill,
    } as unknown as PostHogAPIClient;

    const result = await makeService({ exportSkill }).publishLocalSkill(
      client,
      "/home/.claude/skills/pr-shepherd",
    );

    expect(exportSkill).toHaveBeenCalledWith(
      "/home/.claude/skills/pr-shepherd",
    );
    expect(result).toEqual({ version: 1, skipped: ["assets/logo.png"] });
  });
});

describe("TeamSkillsService.installTeamSkillLocally", () => {
  it("fetches the skill and materializes it with the overwrite flag", async () => {
    const installTeamSkill = vi
      .fn()
      .mockResolvedValue({ path: "/home/.claude/skills/pr-shepherd" });
    const client = {
      getLlmSkillByName: vi.fn().mockResolvedValue({
        name: "pr-shepherd",
        description: "Shepherds PRs",
        body: "# Body",
        files: [],
      }),
    } as unknown as PostHogAPIClient;

    const result = await makeService({
      installTeamSkill,
    }).installTeamSkillLocally(client, "pr-shepherd", true);

    expect(installTeamSkill).toHaveBeenCalledWith({
      name: "pr-shepherd",
      description: "Shepherds PRs",
      body: "# Body",
      files: [],
      overwrite: true,
    });
    expect(result).toEqual({ path: "/home/.claude/skills/pr-shepherd" });
  });
});
