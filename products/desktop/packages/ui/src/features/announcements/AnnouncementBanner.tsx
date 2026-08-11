import { MegaphoneIcon, XIcon } from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import {
  ANALYTICS_EVENTS,
  type AnnouncementProperties,
} from "@posthog/shared/analytics-events";
import type { Announcement } from "@posthog/shared/announcements";
import { track } from "@posthog/ui/shell/analytics";
import { useEffect } from "react";
import { AnnouncementInlineMarkdown } from "./AnnouncementMarkdown";
import { useOpenAnnouncementCta } from "./announcementCta";
import { useAnnouncementsStore } from "./announcementsStore";
import { UpdateAction } from "./UpdateAction";
import { useActiveAnnouncement } from "./useActiveAnnouncement";

type BannerAnnouncement = Extract<Announcement, { kind: "announcement" }>;

export function AnnouncementBanner() {
  const active = useActiveAnnouncement();
  if (
    !active ||
    active.announcement.kind !== "announcement" ||
    active.announcement.style !== "banner"
  ) {
    return null;
  }
  return (
    <BannerRow
      announcement={active.announcement}
      needsUpdate={active.needsUpdate}
    />
  );
}

/** The pure banner row — exported for Storybook; the app renders it through
 * AnnouncementBanner's selection gate above. */
export function BannerRow({
  announcement,
  needsUpdate,
}: {
  announcement: BannerAnnouncement;
  needsUpdate: boolean;
}) {
  const dismiss = useAnnouncementsStore((state) => state.dismiss);
  const openCta = useOpenAnnouncementCta();
  const analytics: AnnouncementProperties = {
    announcement_id: announcement.id,
    announcement_kind: announcement.kind,
    announcement_style: "banner",
  };

  useEffect(() => {
    track(ANALYTICS_EVENTS.ANNOUNCEMENT_SHOWN, {
      announcement_id: announcement.id,
      announcement_kind: announcement.kind,
      announcement_style: "banner",
    });
  }, [announcement.id, announcement.kind]);

  const handleDismiss = () => {
    track(ANALYTICS_EVENTS.ANNOUNCEMENT_DISMISSED, analytics);
    dismiss(announcement.id);
  };

  const handleCta = (url: string) => {
    const ctaType = openCta(url);
    track(ANALYTICS_EVENTS.ANNOUNCEMENT_CTA_CLICKED, {
      ...analytics,
      cta_type: ctaType,
    });
  };

  return (
    <div className="no-drag shrink-0 px-2 pt-2 pb-1">
      <div className="flex w-full items-center gap-2.5 rounded-md border border-(--accent-6) bg-(--accent-3) px-3 py-2 text-(--accent-11) text-[13px]">
        <MegaphoneIcon size={16} weight="duotone" className="shrink-0" />
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="font-medium">{announcement.title}</span>
          <span className="truncate text-(--accent-a11) text-[11px]">
            <AnnouncementInlineMarkdown
              content={announcement.body.split("\n")[0]}
            />
          </span>
        </div>
        {needsUpdate ? (
          <UpdateAction analytics={analytics} />
        ) : announcement.cta ? (
          <Button
            variant="outline"
            size="sm"
            onClick={() => announcement.cta && handleCta(announcement.cta.url)}
          >
            {announcement.cta.label}
          </Button>
        ) : null}
        <button
          type="button"
          aria-label="Dismiss announcement"
          title="Dismiss"
          className="shrink-0 rounded-full p-1 text-(--accent-11) transition-colors hover:bg-(--accent-a4)"
          onClick={handleDismiss}
        >
          <XIcon size={12} weight="bold" />
        </button>
      </div>
    </div>
  );
}
