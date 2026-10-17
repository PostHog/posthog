import { unescapeXmlAttr } from "@posthog/shared";

const PI_SKILL_INVOCATION =
  /^<skill name="([^"]+)" location="[^"]+">\n[\s\S]*?\n<\/skill>(?:\n\n([\s\S]+))?$/;

// The typed form of a Pi skill command, before Pi expands it into a <skill> block.
const PI_SKILL_COMMAND = /^\/skill:(?=[a-zA-Z][\w-]*(?:\s|$))/;

export function collapsePiSkillInvocation(content: string): string {
  if (PI_SKILL_COMMAND.test(content)) {
    return content.replace(PI_SKILL_COMMAND, "/");
  }

  const match = content.match(PI_SKILL_INVOCATION);
  if (!match) {
    return content;
  }

  const name = unescapeXmlAttr(match[1]);
  const userMessage = match[2]?.trim();
  return userMessage ? `/${name}\n\n${userMessage}` : `/${name}`;
}
