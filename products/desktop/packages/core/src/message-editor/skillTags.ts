import { type UploadableSkillSource, unescapeXmlAttr } from "@posthog/shared";

const SKILL_TAG_REGEX = /<skill\b([^>]*?)\s*\/>/g;
const XML_ATTR_REGEX = /(\w+)="([^"]*)"/g;

export interface UploadableSkillTag {
  name: string;
  source: UploadableSkillSource;
  path: string;
}

export function parseXmlAttrs(raw: string): Record<string, string> {
  const attrs: Record<string, string> = {};
  for (const match of raw.matchAll(XML_ATTR_REGEX)) {
    attrs[match[1]] = unescapeXmlAttr(match[2]);
  }
  return attrs;
}

export function isUploadableSkillSource(
  source: string | undefined,
): source is UploadableSkillSource {
  return (
    source === "user" ||
    source === "repo" ||
    source === "marketplace" ||
    source === "codex"
  );
}

export function replaceSkillTags(
  prompt: string,
  replacer: (attrs: Record<string, string>) => string,
): string {
  return prompt.replaceAll(SKILL_TAG_REGEX, (_match, rawAttrs: string) =>
    replacer(parseXmlAttrs(rawAttrs)),
  );
}

export function skillTagsToSlashCommands(prompt: string): string {
  return replaceSkillTags(prompt, (attrs) =>
    attrs.name ? `/${attrs.name}` : "",
  );
}

export function collectUploadableSkillTags(
  prompt: string,
): UploadableSkillTag[] {
  const tags: UploadableSkillTag[] = [];

  replaceSkillTags(prompt, (attrs) => {
    if (attrs.name && attrs.path && isUploadableSkillSource(attrs.source)) {
      tags.push({
        name: attrs.name,
        source: attrs.source,
        path: attrs.path,
      });
    }
    return "";
  });

  return tags;
}
