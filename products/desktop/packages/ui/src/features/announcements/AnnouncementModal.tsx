import {
  Button,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
} from "@posthog/quill";
import {
  ANALYTICS_EVENTS,
  type AnnouncementProperties,
} from "@posthog/shared/analytics-events";
import type { Announcement } from "@posthog/shared/announcements";
import { track } from "@posthog/ui/shell/analytics";
import { useEffect } from "react";
import { AnnouncementHero } from "./AnnouncementHero";
import { AnnouncementMarkdown } from "./AnnouncementMarkdown";
import { useOpenAnnouncementCta } from "./announcementCta";
import { useAnnouncementsStore } from "./announcementsStore";
import { UpdateAction } from "./UpdateAction";
import { useBlockingKeyboardIsolation } from "./useBlockingKeyboardIsolation";

type ModalAnnouncement = Extract<Announcement, { kind: "announcement" }>;

export function AnnouncementModal({
  announcement,
  needsUpdate,
}: {
  announcement: ModalAnnouncement;
  needsUpdate: boolean;
}) {
  const dismiss = useAnnouncementsStore((state) => state.dismiss);
  const undismiss = useAnnouncementsStore((state) => state.undismiss);
  const openCta = useOpenAnnouncementCta();
  const analytics: AnnouncementProperties = {
    announcement_id: announcement.id,
    announcement_kind: announcement.kind,
    announcement_style: "modal",
  };

  useEffect(() => {
    track(ANALYTICS_EVENTS.ANNOUNCEMENT_SHOWN, {
      announcement_id: announcement.id,
      announcement_kind: announcement.kind,
      announcement_style: "modal",
    });
  }, [announcement.id, announcement.kind]);

  const handleClose = () => {
    track(ANALYTICS_EVENTS.ANNOUNCEMENT_DISMISSED, analytics);
    dismiss(announcement.id);
  };

  // Engaging with the CTA retires the announcement the same way closing does.
  const handleCta = (url: string) => {
    const ctaType = openCta(url);
    track(ANALYTICS_EVENTS.ANNOUNCEMENT_CTA_CLICKED, {
      ...analytics,
      cta_type: ctaType,
    });
    dismiss(announcement.id);
  };

  const acknowledge = (ackType: "ok" | "update") => {
    track(ANALYTICS_EVENTS.ANNOUNCEMENT_ACKNOWLEDGED, {
      ...analytics,
      ack_type: ackType,
    });
    dismiss(announcement.id);
  };

  const blocking = announcement.requiresAck;
  // Blocking means the whole app: the overlay stops the pointer, this stops
  // the app's keyboard shortcuts from operating the app behind the modal.
  useBlockingKeyboardIsolation(blocking);

  return (
    <Dialog
      open
      onOpenChange={
        blocking
          ? undefined
          : (open) => {
              if (!open) handleClose();
            }
      }
    >
      {/* DialogBody caps and scrolls the remote-length body so the actions in
          DialogFooter stay reachable on short windows — essential when the
          modal is blocking and the footer is the only way out. initialFocus
          off: default initial focus lands on the body's first link and draws
          a focus ring on open. */}
      <DialogContent
        className="announcement-dialog sm:max-w-md"
        showCloseButton={!blocking}
        initialFocus={false}
      >
        <AnnouncementHero hero={announcement.hero} defaultHedgehog="happy" />
        <DialogBody>
          <DialogTitle className="font-semibold text-[17px] text-gray-12 tracking-tight">
            {announcement.title}
          </DialogTitle>
          <DialogDescription
            render={<div />}
            className="mt-1.5 text-[13px] text-gray-11 leading-relaxed"
          >
            <AnnouncementMarkdown content={announcement.body} />
          </DialogDescription>
        </DialogBody>
        <DialogFooter className="border-t-0 bg-transparent">
          {blocking ? (
            needsUpdate ? (
              <UpdateAction
                analytics={analytics}
                showProgress
                onInstallHandoff={() => acknowledge("update")}
                onInstallFailed={() => undismiss(announcement.id)}
              />
            ) : (
              <Button
                variant="primary"
                size="sm"
                onClick={() => acknowledge("ok")}
              >
                {announcement.ackLabel ?? "OK"}
              </Button>
            )
          ) : (
            <>
              <Button variant="outline" size="sm" onClick={handleClose}>
                Dismiss
              </Button>
              {needsUpdate ? (
                <UpdateAction analytics={analytics} showProgress />
              ) : announcement.cta ? (
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() =>
                    announcement.cta && handleCta(announcement.cta.url)
                  }
                >
                  {announcement.cta.label}
                </Button>
              ) : null}
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
