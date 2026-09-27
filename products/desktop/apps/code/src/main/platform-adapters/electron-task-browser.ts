import {
  createNewWindowLimiter,
  isAllowedTaskBrowserUrl,
} from "@posthog/core/task-browser/guest-policy";
import type { WebContents } from "electron";
import { TASK_BROWSER_PARTITION } from "../../shared/constants";
import { lockDownGuestSession } from "./electron-task-preview";

export function isAllowedTaskBrowser(
  src: string,
  partition: string | undefined,
): boolean {
  return partition === TASK_BROWSER_PARTITION && isAllowedTaskBrowserUrl(src);
}

export function lockDownTaskBrowser(
  guest: WebContents,
  handlers: {
    openInApp: (url: string, source: WebContents) => void;
    mayNavigate: (url: string, source: WebContents) => boolean;
    openExternal: (url: string) => void;
  },
): void {
  const mayOpen = createNewWindowLimiter();
  guest.setWindowOpenHandler(({ url }) => {
    if (!mayOpen()) return { action: "deny" };
    if (isAllowedTaskBrowserUrl(url)) handlers.openInApp(url, guest);
    else handlers.openExternal(url);
    return { action: "deny" };
  });
  guest.setWebRTCIPHandlingPolicy("disable_non_proxied_udp");
  guest.on("will-navigate", (event, url) => {
    if (!isAllowedTaskBrowserUrl(url)) {
      event.preventDefault();
      handlers.openExternal(url);
      return;
    }
    if (!handlers.mayNavigate(url, guest)) event.preventDefault();
  });
  guest.on("will-redirect", (event, url) => {
    if (!event.isMainFrame) return;
    if (!isAllowedTaskBrowserUrl(url) || !handlers.mayNavigate(url, guest)) {
      event.preventDefault();
    }
  });
  lockDownGuestSession(guest.session);
}
