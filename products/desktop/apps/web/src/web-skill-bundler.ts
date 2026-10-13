import type { LocalSkillBundle } from "@posthog/core/sessions/cloudArtifactIdentifiers";
import {
  type ExportedSkill,
  isIgnoredSkillPath,
  serializeSkillMarkdown,
  type UploadableSkillSource,
} from "@posthog/shared";
import { strToU8, zipSync } from "fflate";

// Browser port of workspace-server's skill-bundler. Desktop zips a skill's
// local directory; web has no local skills, so it bundles a TEAM skill fetched
// from the PostHog API (ExportedSkill: SKILL.md body + files) into the exact
// same archive shape the cloud sandbox unpacks — the skill files at their
// relative paths, plus a posthog-skill-bundle.json manifest. SKILL.md is
// reconstructed via the shared serializeSkillMarkdown so it matches desktop.

const SKILL_BUNDLE_MAX_BYTES = 30 * 1024 * 1024;

const CHUNK_SIZE = 8192;
function bytesToBase64(bytes: Uint8Array): string {
  const chunks: string[] = [];
  for (let i = 0; i < bytes.length; i += CHUNK_SIZE) {
    chunks.push(String.fromCharCode(...bytes.subarray(i, i + CHUNK_SIZE)));
  }
  return btoa(chunks.join(""));
}

async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", bytes as BufferSource);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

function safeSkillFileName(name: string): string {
  const base = (name.split("/").pop() ?? name).replace(/[^\w.-]/g, "_");
  return base.length > 0 ? base : "skill";
}

export async function bundleExportedSkill(
  exported: ExportedSkill,
  source: UploadableSkillSource,
): Promise<LocalSkillBundle> {
  const files: Record<string, Uint8Array> = {};
  // SKILL.md is reconstructed from body + frontmatter (the API returns them
  // split), matching how desktop's installTeamSkill writes it to disk.
  files["SKILL.md"] = strToU8(
    serializeSkillMarkdown(
      {
        name: exported.name,
        description: exported.description,
        disableModelInvocation: exported.disableModelInvocation,
      },
      exported.body,
    ),
  );
  for (const file of exported.files) {
    const normalized = file.path.replaceAll("\\", "/");
    if (isIgnoredSkillPath(normalized)) continue;
    if (normalized === "SKILL.md") continue; // body is the source of truth
    files[normalized] = strToU8(file.content);
  }

  // Sorted files, manifest last — mirrors the desktop bundler's ordering.
  const zipInput: Record<string, Uint8Array> = {};
  for (const fileName of Object.keys(files).sort()) {
    zipInput[fileName] = files[fileName];
  }
  zipInput["posthog-skill-bundle.json"] = strToU8(
    JSON.stringify({ schema_version: 1, name: exported.name, source }),
  );

  const zipped = zipSync(zipInput, { level: 6 });
  if (zipped.byteLength > SKILL_BUNDLE_MAX_BYTES) {
    throw new Error("Skill bundle archive exceeds the 30MB cloud run limit");
  }

  return {
    name: exported.name,
    source,
    fileName: `${safeSkillFileName(exported.name)}.zip`,
    contentType: "application/zip",
    contentBase64: bytesToBase64(zipped),
    contentSha256: await sha256Hex(zipped),
    size: zipped.byteLength,
  };
}
