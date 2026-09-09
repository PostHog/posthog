import { useActiveAnnouncement } from "./useActiveAnnouncement";

/** A blocking announcement (required-update or requiresAck) is on stage. */
export function useBlockingAnnouncementVisible(): boolean {
  const active = useActiveAnnouncement();
  if (active === null) return false;
  const { announcement } = active;
  return (
    announcement.kind === "required-update" ||
    (announcement.kind === "announcement" && announcement.requiresAck)
  );
}
