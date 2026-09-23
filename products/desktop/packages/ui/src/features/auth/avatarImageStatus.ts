export type AvatarImageStatus = "loaded" | "error";

// An error is only trusted for a short while. The disk cache answers with 404 both
// when the address has no Gravatar and when it holds no copy and the fetch failed,
// so an avatar that failed while the app was offline must get another try once the
// network is back, instead of staying on initials until the app restarts.
const ERROR_RETRY_AFTER_MS = 60_000;

const statuses = new Map<
  string,
  { status: AvatarImageStatus; recordedAt: number }
>();

export function rememberAvatarImageStatus(
  src: string,
  status: AvatarImageStatus,
): void {
  statuses.set(src, { status, recordedAt: Date.now() });
}

export function rememberedAvatarImageStatus(
  src: string | undefined,
): AvatarImageStatus | undefined {
  const remembered = src ? statuses.get(src) : undefined;
  if (!remembered) return undefined;
  if (
    remembered.status === "error" &&
    Date.now() - remembered.recordedAt >= ERROR_RETRY_AFTER_MS
  ) {
    return undefined;
  }
  return remembered.status;
}
