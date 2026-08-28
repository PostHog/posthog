import { AnnouncementModal } from "./AnnouncementModal";
import { RequiredUpdateModal } from "./RequiredUpdateModal";
import { useActiveAnnouncement } from "./useActiveAnnouncement";

/**
 * Mounts the modal announcement surfaces (the banner mounts separately in the
 * shell).
 */
export function AnnouncementsHost() {
  const active = useActiveAnnouncement();
  if (!active) return null;

  const { announcement } = active;
  if (announcement.kind === "required-update") {
    return <RequiredUpdateModal announcement={announcement} />;
  }
  if (announcement.style === "modal") {
    return (
      <AnnouncementModal
        announcement={announcement}
        needsUpdate={active.needsUpdate}
      />
    );
  }
  return null;
}
