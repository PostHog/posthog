import type { ReadFileAsBase64 } from "@posthog/core/editor/cloud-prompt";
import { base64ToText } from "@posthog/core/files/base64";
import type { FileReadClient } from "@posthog/core/files/identifiers";
import type {
  BundleLocalSkill,
  ResolveSkillBundleDependencies,
} from "@posthog/core/sessions/cloudArtifactIdentifiers";
import type {
  GithubPrTitleClient,
  TitleGeneratorLogger,
} from "@posthog/core/sessions/titleGeneratorIdentifiers";
import { TEAM_SKILLS_SERVICE } from "@posthog/core/skills/identifiers";
import type { TeamSkillsService } from "@posthog/core/skills/teamSkillsService";
import { resolveService } from "@posthog/di/container";
import type { RootLogger } from "@posthog/di/logger";
import { getAuthenticatedClient } from "@posthog/ui/features/auth/authClientImperative";
import { getWebAttachmentBase64 } from "./web-attachment-store";
import { bundleExportedSkill } from "./web-skill-bundler";

// CloudArtifactService + TitleGeneratorService (sessionsModule) depend on a
// handful of clients that, on desktop, read the local filesystem or bundle local
// skills. The cloud-only web host has neither, so these are adapted:
//   - attachment bytes come from an in-memory store keyed by the synthetic id
//     the os.saveClipboard* handlers minted (see web-attachment-store)
//   - skills are TEAM skills fetched from the API and bundled client-side (a
//     cloud task references them tagged source "user"; see web-skill-bundler)
// The services themselves are portable core and bind unchanged via sessionsModule.

// Resolve an attachment id to its base64 bytes for cloud upload. On web the id
// is a synthetic key into the in-memory store (not a filesystem path).
export const webReadFileAsBase64: ReadFileAsBase64 = (filePath: string) =>
  Promise.resolve(getWebAttachmentBase64(filePath));

export const webGithubPrTitleClient: GithubPrTitleClient = {
  getGithubPullRequestTitle: async ({ owner, repo, number }) => {
    let response: Response;
    try {
      response = await fetch(
        `https://api.github.com/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/pulls/${number}`,
        {
          headers: { Accept: "application/vnd.github+json" },
          signal: AbortSignal.timeout(5_000),
        },
      );
    } catch {
      return null;
    }
    if (!response.ok) return null;
    const payload: unknown = await response.json();
    if (
      typeof payload !== "object" ||
      payload === null ||
      !("title" in payload) ||
      typeof payload.title !== "string"
    ) {
      return null;
    }
    return payload.title;
  },
};

// A skill referenced in a cloud-task message is a TEAM skill (the web / menu
// lists team skills). Fetch its content from the PostHog API and zip it in the
// browser into the same bundle shape the sandbox expects.
export const webBundleLocalSkill: BundleLocalSkill = async (ref) => {
  const client = await getAuthenticatedClient();
  if (!client) {
    throw new Error("Not authenticated; cannot bundle skill for the cloud run");
  }
  const service = resolveService<TeamSkillsService>(TEAM_SKILLS_SERVICE);
  const exported = await service.fetchSkillForInstall(client, ref.name);
  return bundleExportedSkill(exported, ref.source);
};

// Dependency-graph expansion is a passthrough on web — and can't be more than
// that with the current team-skills pipeline. A skill declares dependencies in
// its SKILL.md frontmatter (`dependencies:`), but the publish path strips
// frontmatter (SkillsService.exportSkill -> stripFrontmatter) and the team-skills
// API carries no dependencies field, so a skill fetched via fetchSkillForInstall
// returns a frontmatter-less body with nothing to expand from. (Desktop only
// expands LOCAL on-disk skills, reading SKILL.md directly — web has none.)
// Making this real requires carrying `dependencies` end-to-end: exportSkill ->
// the publish payload -> the LlmSkill API (backend) -> fetchSkillForInstall.
// Until then a skill that depends on another must be picked explicitly.
export const webResolveSkillBundleDependencies: ResolveSkillBundleDependencies =
  (refs) => Promise.resolve(refs);

// Naming a task reads the text a user pasted or dropped into the composer. Web
// has no filesystem, but that text is already in the attachment store under the
// same synthetic id, so decode it back from the stored bytes. Anything not in
// the store — a real path carried by a cloud task made on desktop — stays
// unreadable here.
export const webFileReadClient: FileReadClient = {
  readAbsoluteFile: (filePath: string) => {
    const base64 = getWebAttachmentBase64(filePath);
    if (!base64) {
      return Promise.resolve(null);
    }
    try {
      return Promise.resolve(base64ToText(base64));
    } catch {
      return Promise.resolve(null);
    }
  },
};

export function webTitleGeneratorLogger(
  logger: RootLogger,
): TitleGeneratorLogger {
  const scoped = logger.scope("title-generator");
  return { error: (message, data) => scoped.error(message, data) };
}
