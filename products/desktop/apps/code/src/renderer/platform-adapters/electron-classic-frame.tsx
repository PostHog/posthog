import type { ClassicFrameProps } from "@posthog/ui/features/classic/classicFrameHost";
import { type ReactElement, useEffect, useRef } from "react";

export function ElectronClassicFrame({
  url,
  accountId,
  onStatusChange,
}: ClassicFrameProps): ReactElement {
  const mountRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;
    onStatusChange("loading");
    const guest = document.createElement("webview");
    guest.className = "flex size-full";
    guest.setAttribute("aria-label", "PostHog web app");
    guest.setAttribute(
      "partition",
      `posthog-classic-${new URL(url).hostname.replaceAll(".", "-")}-${accountId}`,
    );
    const target = new URL(url);
    target.searchParams.set("__desktop_classic", "1");
    target.searchParams.set("__desktop_parent_origin", target.origin);
    guest.setAttribute("src", target.href);
    const ready = (): void => onStatusChange("ready");
    const failed = (event: Event): void => {
      const failure = event as Event & {
        errorCode?: number;
        isMainFrame?: boolean;
      };
      if (failure.errorCode !== -3 && failure.isMainFrame !== false)
        onStatusChange("error");
    };
    const gone = (): void => onStatusChange("error");
    guest.addEventListener("dom-ready", ready);
    guest.addEventListener("did-fail-load", failed);
    guest.addEventListener("render-process-gone", gone);
    mount.appendChild(guest);
    const timeout = window.setTimeout(() => onStatusChange("error"), 30000);
    const clearTimeout = (): void => window.clearTimeout(timeout);
    guest.addEventListener("dom-ready", clearTimeout);
    return () => {
      window.clearTimeout(timeout);
      guest.removeEventListener("dom-ready", ready);
      guest.removeEventListener("dom-ready", clearTimeout);
      guest.removeEventListener("did-fail-load", failed);
      guest.removeEventListener("render-process-gone", gone);
      guest.remove();
    };
  }, [url, accountId, onStatusChange]);

  return <div ref={mountRef} className="size-full" />;
}
