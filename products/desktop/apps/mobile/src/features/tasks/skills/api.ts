import { authedFetch, getBaseUrl, getProjectId } from "@/lib/api";
import type { SkillStoreListEntry, SkillStoreSkill } from "./types";

function skillStoreBaseUrl(): string {
  const baseUrl = getBaseUrl();
  const projectId = getProjectId();
  return `${baseUrl}/api/environments/${projectId}/llm_skills`;
}

async function readJsonOrThrow<T>(
  response: Response,
  errorPrefix: string,
): Promise<T> {
  if (!response.ok) {
    const data = (await response.json().catch(() => ({}))) as {
      detail?: string;
    };
    throw new Error(data.detail ?? `${errorPrefix}: ${response.statusText}`);
  }

  return (await response.json()) as T;
}

export async function getSkillStoreSkills(): Promise<SkillStoreListEntry[]> {
  const response = await authedFetch(`${skillStoreBaseUrl()}/`);

  const data = await readJsonOrThrow<
    SkillStoreListEntry[] | { results?: SkillStoreListEntry[] }
  >(response, "Failed to fetch skills");

  return Array.isArray(data) ? data : (data.results ?? []);
}

export async function getSkillStoreSkill(
  skillName: string,
): Promise<SkillStoreSkill> {
  const response = await authedFetch(
    `${skillStoreBaseUrl()}/name/${encodeURIComponent(skillName)}/`,
  );

  return readJsonOrThrow<SkillStoreSkill>(response, "Failed to fetch skill");
}
