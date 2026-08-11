import { ANNOUNCEMENTS_FLAG } from "@posthog/shared";
import { readSuppressChangelog } from "@posthog/shared/announcements";
import { useFeatureFlagPayload } from "../feature-flags/useFeatureFlagPayload";

/** The payload's changelog policy: on-stage announcements cancel it (default). */
export function useSuppressChangelog(): boolean {
  const payload = useFeatureFlagPayload(ANNOUNCEMENTS_FLAG);
  return readSuppressChangelog(payload);
}
