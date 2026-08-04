const ORCHESTRATION_INSTRUCTIONS_REGEX =
  /<orchestration_instructions\b[^>]*>(\r?\nThe following system-generated instructions apply to this orchestrated child run\. Follow them\.\r?\n\r?\n[\s\S]*?)<\/orchestration_instructions>/;

export function extractOrchestrationInstructions(content: string): {
  body: string;
  stripped: string;
} | null {
  const match = ORCHESTRATION_INSTRUCTIONS_REGEX.exec(content);
  if (match?.index === undefined) return null;

  const body = match[1].trim();
  const stripped = (
    content.slice(0, match.index) + content.slice(match.index + match[0].length)
  ).trim();

  return { body, stripped };
}
