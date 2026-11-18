/**
 * A model's name without the vendor word that every Claude model repeats.
 *
 * The composer toolbar holds the model, the reasoning effort, the permission mode and
 * the run's status on one line, so the seven characters in "Claude " cost more room
 * than they carry: "Sonnet 5" and "Opus 5" name the model on their own.
 *
 * Only the model families are stripped. "Claude Code" names a harness rather than a
 * model, and "Code" alone would not say that. Labels reach a picker from the agent at
 * runtime rather than from the catalog, so a name this does not recognize is returned
 * as it came in.
 */
const CLAUDE_MODEL_FAMILY = /^Claude (?=(?:Opus|Sonnet|Haiku|Fable)\b)/;

export function shortModelLabel(label: string): string {
  return label.replace(CLAUDE_MODEL_FAMILY, "");
}
