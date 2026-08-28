// The first-run session's whole prompt arrives wrapped in `<onboarding_brief>` (see
// ONBOARDING_PROMPT_TAG in the tasks facade). Nobody typed it, so the conversation shows a chip
// in its place rather than the brief itself — and a chip rather than nothing, because the block
// is the entire message and stripping it would leave an empty bubble.
const ONBOARDING_BRIEF_REGEX =
  /<onboarding_brief\b[^>]*>[\s\S]*?<\/onboarding_brief>/;

export const ONBOARDING_BRIEF_LABEL = "Getting started with PostHog Desktop";

export function extractOnboardingBrief(
  content: string,
): { stripped: string } | null {
  const match = ONBOARDING_BRIEF_REGEX.exec(content);
  if (match?.index === undefined) return null;
  return {
    stripped: (
      content.slice(0, match.index) +
      content.slice(match.index + match[0].length)
    ).trim(),
  };
}
