export function canPromptPiSession(
  taskAuthorUuid: string | undefined,
  currentUserUuid: string | undefined,
): boolean {
  return !taskAuthorUuid || taskAuthorUuid === currentUserUuid;
}
