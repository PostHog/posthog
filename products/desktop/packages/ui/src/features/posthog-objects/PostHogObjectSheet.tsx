import { useService } from "@posthog/di/react";
import {
  EMBEDDED_WEB_APP_SOURCE,
  type IEmbeddedWebAppSource,
} from "@posthog/platform/embedded-web-app";
import { Dialog, DialogContent, DialogTitle } from "@posthog/quill";
import { useRouterState } from "@tanstack/react-router";
import { useEffect, useLayoutEffect, useMemo } from "react";
import { useObjectSheetStore } from "./objectSheetStore";
import { PostHogObjectPage } from "./PostHogObjectPage";

/**
 * Opens a PostHog object referenced outside a session (Today, a report, the activity feed) over the
 * current page, where it used to open in the browser. Mounted once, under the Today, Ask and Library
 * layout. Mounting it is what turns the sheet on.
 */
export function PostHogObjectSheet() {
  const source = useService<IEmbeddedWebAppSource>(EMBEDDED_WEB_APP_SOURCE);
  const libraryAvailable = useMemo(() => source.getConfig() !== null, [source]);
  const object = useObjectSheetStore((state) => state.object);
  const setAvailability = useObjectSheetStore((state) => state.setAvailability);
  const closeObject = useObjectSheetStore((state) => state.closeObject);
  const href = useRouterState({ select: (state) => state.location.href });

  useLayoutEffect(() => {
    setAvailability({ sheetEnabled: true, libraryAvailable });
    return () => {
      setAvailability({ sheetEnabled: false, libraryAvailable: false });
      closeObject();
    };
  }, [libraryAvailable, setAvailability, closeObject]);

  // "Open in Library" and any other navigation leave the page the sheet sits on.
  // biome-ignore lint/correctness/useExhaustiveDependencies: `href` is the trigger.
  useEffect(() => {
    closeObject();
  }, [href, closeObject]);

  return (
    <Dialog
      open={object !== null}
      onOpenChange={(open) => {
        if (!open) closeObject();
      }}
    >
      <DialogContent className="h-[85vh] max-w-5xl overflow-hidden p-0 sm:max-w-5xl">
        <DialogTitle className="sr-only">{object?.name ?? ""}</DialogTitle>
        {object && (
          <PostHogObjectPage
            key={`${object.kind}:${object.id}`}
            metadata={{ object_kind: object.kind, object_id: object.id }}
            fallbackName={object.name}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
