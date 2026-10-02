const VALIDATION_COMMAND =
  /(?:^|[;&|()\n])\s*(?:(?:env|exec|time)\s+)?(?:(?:pnpm|npm|yarn|bun)\b[^;&|\n]*\b(?:test|build|typecheck|typescript:check)\b[^;&|\n]*|(?:uv\s+run\s+)?(?:pytest|jest|vitest|tsc|tsgo)\b[^;&|\n]*|(?:cargo|go)\s+(?:test|build|check)\b[^;&|\n]*)/;

export const VALIDATION_LOCK_PREFIX = [
  "exec {__posthog_validation_lock_fd}>/tmp/posthog-memory-validation.lock",
  'if ! flock -n "$__posthog_validation_lock_fd"; then',
  '  printf "%s\\n" "Another build, test suite, or typecheck is running in this sandbox. Let it finish before starting more validation, including in other worktrees." >&2',
  "  exit 75",
  "fi",
  "",
].join("\n");

export function validationCommandKey(command: string): string | undefined {
  const original = command.startsWith(VALIDATION_LOCK_PREFIX)
    ? command.slice(VALIDATION_LOCK_PREFIX.length)
    : command;
  const validation = VALIDATION_COMMAND.exec(original);
  if (!validation) return undefined;
  return (
    original.slice(0, validation.index) +
    validation[0].replace(/\s+\d*>{1,2}.*$/, "")
  ).trim();
}

export function serializeValidation(command: string): string {
  return command.startsWith(VALIDATION_LOCK_PREFIX)
    ? command
    : VALIDATION_LOCK_PREFIX + command;
}
