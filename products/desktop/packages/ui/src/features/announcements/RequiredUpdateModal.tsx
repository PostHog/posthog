import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type { Announcement } from "@posthog/shared/announcements";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { track } from "@posthog/ui/shell/analytics";
import { useEffect } from "react";
import { AnnouncementHero } from "./AnnouncementHero";
import { UpdateAction } from "./UpdateAction";

type RequiredUpdate = Extract<Announcement, { kind: "required-update" }>;

/**
 * Blocking: stays open until the user updates. Controlled `open` with no
 * onOpenChange means Esc and outside clicks change nothing, and the close
 * button is suppressed — the only way forward is the update action. That is
 * also why the body renders inside DialogBody: the remote-length content must
 * scroll rather than push the sole update action out of a short viewport.
 */
export function RequiredUpdateModal({
  announcement,
}: {
  announcement: RequiredUpdate;
}) {
  useEffect(() => {
    track(ANALYTICS_EVENTS.ANNOUNCEMENT_SHOWN, {
      announcement_id: announcement.id,
      announcement_kind: announcement.kind,
      announcement_style: "modal",
    });
  }, [announcement.id, announcement.kind]);

  return (
    <Dialog open>
      <DialogContent className="sm:max-w-md" showCloseButton={false}>
        <AnnouncementHero
          hero={announcement.hero}
          defaultHedgehog="builder"
          defaultColor="#f54e00"
        />
        <DialogBody>
          <DialogTitle className="font-semibold text-[17px] text-gray-12 tracking-tight">
            {announcement.title}
          </DialogTitle>
          <DialogDescription
            render={<div />}
            className="mt-1.5 text-[13px] text-gray-11 leading-relaxed"
          >
            <MarkdownRenderer content={announcement.body} />
          </DialogDescription>
        </DialogBody>
        <DialogFooter>
          <UpdateAction
            analytics={{
              announcement_id: announcement.id,
              announcement_kind: announcement.kind,
              announcement_style: "modal",
            }}
            showProgress
          />
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
