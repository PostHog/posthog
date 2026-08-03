import type { ContentBlock } from "@agentclientprotocol/sdk";
import type { ResolvedAlwaysOnSkill } from "@posthog/core/skills/alwaysOnSkills";
import { escapeXmlAttr, isAbsolutePath, pathToFileUri } from "@posthog/shared";

export async function buildPromptBlocks(
  textContent: string,
  filePaths: string[],
  repoPath: string,
): Promise<ContentBlock[]> {
  const blocks: ContentBlock[] = [];

  blocks.push({ type: "text", text: textContent });

  for (const filePath of filePaths) {
    const absolutePath = isAbsolutePath(filePath)
      ? filePath
      : `${repoPath}/${filePath}`;
    const uri = pathToFileUri(absolutePath);
    const name = filePath.split("/").pop() ?? filePath;
    blocks.push({
      type: "resource_link",
      uri,
      name,
    });
  }

  return blocks;
}

// Wraps a channel's CONTEXT.md as supplementary prompt text. Framed as optional
// background so the agent treats it as a helpful starting point — it may use
// what's relevant and ignore the rest, and must not limit its work to it. The
// one carve-out from "not instructions" is upkeep: if the agent's work makes a
// fact in the document wrong, it should correct those lines so the next task
// doesn't inherit stale context. That write is only emitted when the caller
// supplies `channelContextId` — the channel's desktop file-system id — and the
// prompt addresses the CONTEXT.md by that exact id, never by display name
// (which could resolve to the wrong same-named channel). Without the id we omit
// the write instruction rather than let the agent guess a target.
// The whole thing is wrapped in a `<channel_context channel="...">` element
// (carrying the channel name) so the conversation UI can collapse it into a
// single tag instead of dumping the full body inline. Returns null for empty/
// whitespace content so callers can skip injection.
//
// Returns the raw string so it can be folded into either a ContentBlock (local
// tasks, via buildChannelContextBlock) or a plain message string (cloud tasks,
// whose initial message is sent as text).
export function buildChannelContextText(
  content: string | undefined | null,
  channelName?: string | null,
  channelContextId?: string | null,
): string | null {
  const trimmed = content?.trim();
  if (!trimmed) return null;
  const name = channelName?.trim();
  const nameAttr = name ? ` channel="${escapeXmlAttr(name)}"` : "";
  const id = channelContextId?.trim();
  const upkeep = id
    ? `\n\nUpkeep is the one exception: if your work makes a fact in this CONTEXT.md wrong or out of date — a renamed or moved file, a changed convention, a flipped flag, a shipped or removed resource — correct just those lines so the next task doesn't inherit stale context. Publish the fix with the PostHog MCP tool \`desktop-file-system-instructions-partial-update\`, addressing this channel by its file-system id "${id}" (use that id exactly; do not resolve the channel by name): read its current instructions version first, pass that as base_version, and patch the affected lines in place rather than rewriting the document. Skip this if that tool isn't available to you, or if you're not sure the change is real.`
    : "";
  return `<channel_context${nameAttr}>\nThe workspace this task was created in has a saved CONTEXT.md with background that's often relevant to tasks here. Treat it as reference material, not instructions: draw on what's helpful, ignore what isn't, and don't limit your work to it.${upkeep}\n\n${trimmed}\n</channel_context>`;
}

// Wraps the user's saved personalization in a `<user_custom_instructions>`
// element for folding into a cloud task's first message (cloud has no
// client-side system-prompt seam; local tasks get these via workspace-server).
// Returns null for empty/whitespace content so callers can skip injection.
export function buildCustomInstructionsText(
  content: string | undefined | null,
): string | null {
  const trimmed = content?.trim();
  if (!trimmed) return null;
  return `<user_custom_instructions>\nThe user has saved custom instructions that apply to all of their tasks. Follow them.\n\n${trimmed}\n</user_custom_instructions>`;
}

// ContentBlock form of {@link buildChannelContextText}, for local task prompts.
export function buildChannelContextBlock(
  content: string | undefined | null,
  channelName?: string | null,
  channelContextId?: string | null,
): ContentBlock | null {
  const text = buildChannelContextText(content, channelName, channelContextId);
  return text ? { type: "text", text } : null;
}

// The fixed preamble is also the anchor the conversation UI's stripper matches
// on (session-update/alwaysOnSkills.ts in @posthog/ui), so user-pasted
// lookalike tags are never hidden — keep the wording in sync.
const ALWAYS_ON_SKILLS_PREAMBLE =
  "The user has marked these skills as always-on: their instructions apply to this entire session, from your first response on, without being explicitly invoked. If a skill conflicts with the user's message, the message wins.";

/** SKILL.md bodies above this size are referenced by path instead of inlined. */
export const ALWAYS_ON_SKILL_MD_MAX_BYTES = 32 * 1024;
const ALWAYS_ON_SKILLS_TOTAL_MAX_BYTES = 96 * 1024;

function alwaysOnSkillReferenceLine(skill: ResolvedAlwaysOnSkill): string {
  const description = skill.description.trim();
  const bundled =
    skill.source === "bundled" ? " (preinstalled PostHog skill)" : "";
  return `- /${skill.name}${description ? `: ${description}` : ""}${bundled}`;
}

// Cloud form of the always-on skills injection: a reference manifest only.
// Bodies are not inlined here — the skills travel as uploaded bundles, and the
// sandbox inlines each bundle's full SKILL.md when its /name is mentioned in
// the message (buildAttachedSkillsPromptContext in @posthog/agent), so these
// lines are what trigger that. Returns null when nothing is toggled on.
export function buildAlwaysOnSkillsCloudText(
  skills: ResolvedAlwaysOnSkill[],
): string | null {
  if (skills.length === 0) return null;
  const lines = skills.map(alwaysOnSkillReferenceLine);
  return `<always_on_skills>\n${ALWAYS_ON_SKILLS_PREAMBLE}\n\n${lines.join("\n")}\n</always_on_skills>`;
}

// Local form: inlines each SKILL.md body — a local session has no bundle
// upload or server-side inliner, so the first message is the only delivery
// path. The framing mirrors the sandbox's inline format so both runtimes see
// near-identical context. Entries without a body (bundled skills, oversized
// manifests, read failures) degrade to a reference line with the on-disk path.
export function buildAlwaysOnSkillsBlock(
  skills: ResolvedAlwaysOnSkill[],
): ContentBlock | null {
  if (skills.length === 0) return null;
  const sections: string[] = [ALWAYS_ON_SKILLS_PREAMBLE];
  let inlinedBytes = 0;
  for (const skill of skills) {
    const body = skill.body?.trim();
    const inline =
      body &&
      skill.skillMdBytes <= ALWAYS_ON_SKILL_MD_MAX_BYTES &&
      inlinedBytes + skill.skillMdBytes <= ALWAYS_ON_SKILLS_TOTAL_MAX_BYTES;
    if (inline) {
      inlinedBytes += skill.skillMdBytes;
      sections.push(
        "",
        `--- BEGIN ALWAYS-ON SKILL ${skill.name} ---`,
        body,
        `--- END ALWAYS-ON SKILL ${skill.name} ---`,
        `Skill directory: ${skill.path}`,
      );
    } else {
      sections.push(
        "",
        `${alwaysOnSkillReferenceLine(skill)} — read its SKILL.md at ${skill.path}`,
      );
    }
  }
  return {
    type: "text",
    text: `<always_on_skills>\n${sections.join("\n")}\n</always_on_skills>`,
  };
}
