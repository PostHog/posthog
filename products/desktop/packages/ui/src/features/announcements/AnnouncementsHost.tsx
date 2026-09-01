import { useUpdateInterruptStore } from "@posthog/ui/features/updates/updateInterruptStore";
import { AnnouncementModal } from "./AnnouncementModal";
import { RequiredUpdateModal } from "./RequiredUpdateModal";
import { useActiveAnnouncement } from "./useActiveAnnouncement";

/**
 * Mounts the modal announcement surfaces (the banner mounts separately in the
 * shell).
 */
export function AnnouncementsHost() {
  const active = useActiveAnnouncement();
  // "Restart when finished" arms a wait that only clears once the agents go
  // idle, which can need the user to reach a task and grant a permission. A
  // blocking modal traps the pointer and keyboard for the whole app, so it
  // would stall that wait indefinitely — step it aside while the wait is
  // armed. The announcement is only acknowledged at the install handoff, so
  // cancelling the wait brings it back.
  const waitingForIdle = useUpdateInterruptStore((s) => s.waitingForIdle);
  if (!active) return null;

  const { announcement } = active;
  if (announcement.kind === "required-update") {
    return waitingForIdle ? null : (
      <RequiredUpdateModal announcement={announcement} />
    );
  }
  if (announcement.style === "modal") {
    if (waitingForIdle && announcement.requiresAck) return null;
    return (
      <AnnouncementModal
        announcement={announcement}
        needsUpdate={active.needsUpdate}
      />
    );
  }
  return null;
}
