import type { ReadFileAsBase64 } from "@posthog/core/editor/cloud-prompt";
import type {
  BundleLocalSkill,
  ResolveSkillBundleDependencies,
} from "@posthog/core/sessions/cloudArtifactIdentifiers";
import type {
  FileReadClient,
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

// Title generator reads referenced files to enrich the title prompt; none exist
// locally on web.
export const webTitleGeneratorFileReadClient: FileReadClient = {
  readAbsoluteFile: () => Promise.resolve(null),
};

export function webTitleGeneratorLogger(
  logger: RootLogger,
): TitleGeneratorLogger {
  const scoped = logger.scope("title-generator");
  return { error: (message, data) => scoped.error(message, data) };
}
