import type { ClassicFrameProps } from "@posthog/ui/features/classic/classicFrameHost";
import { type ReactElement, useEffect, useRef } from "react";

export function WebClassicFrame({
  url,
  accountId,
  onStatusChange,
}: ClassicFrameProps): ReactElement {
  const mountRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;
    const target = new URL(url);
    const projectId = target.pathname.match(
      /^\/project\/(\d+)\/dashboards?\/?$/,
    )?.[1];
    target.searchParams.set("__desktop_classic", "1");
    target.searchParams.set("__desktop_parent_origin", window.location.origin);
    const frame = document.createElement("iframe");
    frame.title = "PostHog web dashboards";
    frame.className = "size-full border-0";
    frame.setAttribute(
      "sandbox",
      "allow-scripts allow-same-origin allow-forms allow-downloads",
    );
    frame.src = target.href;
    let timeout: ReturnType<typeof setTimeout>;
    const loading = (): void => {
      onStatusChange("loading");
      clearTimeout(timeout);
      timeout = setTimeout(
        () =>
          onStatusChange(
            "error",
            "Open the web app and sign in with the same account. Then reload dashboards. The web app must include Classic support and allow this browser host.",
          ),
        15000,
      );
    };
    const receive = (event: MessageEvent): void => {
      if (
        event.source !== frame.contentWindow ||
        event.origin !== target.origin ||
        event.data?.type !== "posthog:classic:status"
      )
        return;
      const {
        status,
        accountId: frameAccountId,
        projectId: frameProjectId,
      } = event.data;
      if (status === "loading") {
        loading();
        return;
      }
      clearTimeout(timeout);
      if (
        status === "ready" &&
        frameAccountId === accountId &&
        frameProjectId === projectId
      ) {
        onStatusChange("ready");
      } else {
        onStatusChange(
          "error",
          "This page or account does not match Classic. Open the web app to check your account, then reload dashboards.",
        );
      }
    };
    const loaded = (): void => {
      loading();
      frame.contentWindow?.postMessage(
        { type: "posthog:classic:ping" },
        target.origin,
      );
    };
    window.addEventListener("message", receive);
    frame.addEventListener("load", loaded);
    loading();
    mount.appendChild(frame);
    return () => {
      clearTimeout(timeout);
      window.removeEventListener("message", receive);
      frame.removeEventListener("load", loaded);
      frame.remove();
    };
  }, [url, accountId, onStatusChange]);

  return <div ref={mountRef} className="size-full" />;
}

WebClassicFrame.supportsUrl = (url: string): boolean => {
  const target = new URL(url);
  return (
    target.protocol === "https:" ||
    (target.protocol === "http:" && target.hostname === "localhost")
  );
};
