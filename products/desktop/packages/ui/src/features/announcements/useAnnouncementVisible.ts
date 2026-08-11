import { useActiveAnnouncement } from "./useActiveAnnouncement";

/** Any remote announcement is on stage — lower-priority surfaces defer. */
export function useAnnouncementVisible(): boolean {
  return useActiveAnnouncement() !== null;
}

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
