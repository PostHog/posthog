import type {
  LlmSkillListItem,
  PostHogAPIClient,
} from "@posthog/api-client/posthog-client";
import type { ExportedSkill } from "@posthog/shared";
import { inject, injectable } from "inversify";
import { SKILLS_WORKSPACE_CLIENT } from "./identifiers";

export type { ExportedSkill };

export interface TeamSkillInfo {
  id: string;
  name: string;
  description: string;
  version: number;
  updatedAt: string;
  createdByEmail: string | null;
  /** A local skill with the same name already exists on this machine. */
  installedLocally: boolean;
}

export interface TeamSkillsListing {
  /** False when the org does not have the team-skills feature enabled. */
  available: boolean;
  skills: TeamSkillInfo[];
}

/** The slice of workspace-server this service needs, bound by the host. */
export interface SkillsWorkspaceClient {
  exportSkill(
    skillPath: string,
  ): Promise<ExportedSkill & { skipped: string[] }>;
  installTeamSkill(
    input: ExportedSkill & { overwrite: boolean },
  ): Promise<{ path: string }>;
}

/**
 * Marks team skills that already exist locally by name. Pure, so callers
 * can re-apply it when the local listing changes without refetching.
 */
export function markInstalledTeamSkills(
  listing: TeamSkillsListing,
  localSkillNames: string[],
): TeamSkillsListing {
  const localNames = new Set(localSkillNames);
  return {
    ...listing,
    skills: listing.skills.map((skill) => ({
      ...skill,
      installedLocally: localNames.has(skill.name),
    })),
  };
}

@injectable()
export class TeamSkillsService {
  constructor(
    @inject(SKILLS_WORKSPACE_CLIENT)
    private readonly workspace: SkillsWorkspaceClient,
  ) {}

  /** Exports the local skill from disk, then creates or versions the team copy. */
  async publishLocalSkill(
    client: PostHogAPIClient,
    skillPath: string,
  ): Promise<{ version: number; skipped: string[] }> {
    const exported = await this.workspace.exportSkill(skillPath);
    const { version } = await this.publishSkill(client, exported);
    return { version, skipped: exported.skipped };
  }

  /** Materializes a team skill into the local user skills dir (copy-and-forget). */
  async installTeamSkillLocally(
    client: PostHogAPIClient,
    name: string,
    overwrite = false,
  ): Promise<{ path: string }> {
    const skill = await this.fetchSkillForInstall(client, name);
    return this.workspace.installTeamSkill({ ...skill, overwrite });
  }

  /**
   * Lists the team's latest skills, owning the availability decision
   * (flag off → absent group, no errors). Combine with
   * markInstalledTeamSkills for the merged local+team view.
   */
  async listTeamSkills(client: PostHogAPIClient): Promise<TeamSkillsListing> {
    const items = await client.listLlmSkills();
    if (items === null) {
      return { available: false, skills: [] };
    }
    return {
      available: true,
      skills: items.filter((item) => item.is_latest).map(toTeamSkillInfo),
    };
  }

  /**
   * Publishes a local skill to the team: creates the LLMSkill on first
   * publish, otherwise publishes a new version against the current latest
   * (versioning comes free from the model's version/is_latest).
   */
  async publishSkill(
    client: PostHogAPIClient,
    exported: ExportedSkill,
  ): Promise<{ version: number }> {
    if (!exported.name.trim()) {
      throw new Error("The skill needs a name before it can be published");
    }
    if (!exported.description.trim()) {
      throw new Error(
        "Add a description before publishing — teammates' agents rely on it",
      );
    }

    const items = await client.listLlmSkills();
    if (items === null) {
      throw new Error("Team skills are not enabled for this organization");
    }
    const existing = items.find(
      (item) => item.name === exported.name && item.is_latest,
    );

    const published = existing
      ? await client.publishLlmSkillVersion(exported.name, {
          body: exported.body,
          description: exported.description,
          files: exported.files,
          base_version: existing.latest_version ?? existing.version,
        })
      : await client.createLlmSkill({
          name: exported.name,
          description: exported.description,
          body: exported.body,
          files: exported.files,
        });

    return { version: published.version };
  }

  /**
   * Fetches everything needed to materialize a team skill on disk: the
   * latest body plus every companion file's content.
   */
  async fetchSkillForInstall(
    client: PostHogAPIClient,
    name: string,
  ): Promise<ExportedSkill> {
    const detail = await client.getLlmSkillByName(name);
    const files = await Promise.all(
      detail.files.map(async (manifest) => {
        const file = await client.getLlmSkillFile(name, manifest.path);
        return { path: file.path, content: file.content };
      }),
    );
    return {
      name: detail.name,
      description: detail.description,
      body: detail.body,
      files,
    };
  }
}

function toTeamSkillInfo(item: LlmSkillListItem): TeamSkillInfo {
  return {
    id: item.id,
    name: item.name,
    description: item.description,
    version: item.latest_version ?? item.version,
    updatedAt: item.updated_at,
    createdByEmail: item.created_by?.email ?? null,
    installedLocally: false,
  };
}
