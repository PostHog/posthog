import { unescapeXmlAttr } from "@posthog/shared";

const PI_SKILL_INVOCATION =
  /^<skill name="([^"]+)" location="[^"]+">\n[\s\S]*?\n<\/skill>(?:\n\n([\s\S]+))?$/;

export function collapsePiSkillInvocation(content: string): string {
  const match = content.match(PI_SKILL_INVOCATION);
  if (!match) {
    return content;
  }

  const name = unescapeXmlAttr(match[1]);
  const userMessage = match[2]?.trim();
  return userMessage ? `/${name}\n\n${userMessage}` : `/${name}`;
}
