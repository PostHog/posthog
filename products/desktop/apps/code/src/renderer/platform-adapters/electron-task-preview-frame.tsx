import type { TaskPreviewFrameProps } from "@posthog/ui/features/task-preview/taskPreviewFrameHost";
import { useEffect, useRef } from "react";
import { TASK_PREVIEW_PARTITION } from "../../shared/constants";

type WebviewLoadFailureEvent = Event & {
  errorCode?: number;
  isMainFrame?: boolean;
};

const ABORTED_LOAD_ERROR_CODE = -3;

export function ElectronTaskPreviewFrame({
  url,
  title,
  onLoadFailed,
}: TaskPreviewFrameProps) {
  const mountRef = useRef<HTMLDivElement>(null);
  const onLoadFailedRef = useRef(onLoadFailed);

  useEffect(() => {
    onLoadFailedRef.current = onLoadFailed;
  }, [onLoadFailed]);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    const webview = document.createElement("webview");
    webview.className = "size-full";
    webview.setAttribute("partition", TASK_PREVIEW_PARTITION);
    webview.setAttribute("src", url);

    const onFailed = (event: Event) => {
      const failure = event as WebviewLoadFailureEvent;
      if (
        failure.isMainFrame === false ||
        failure.errorCode === ABORTED_LOAD_ERROR_CODE
      ) {
        return;
      }
      onLoadFailedRef.current();
    };
    const onGone = () => onLoadFailedRef.current();

    webview.addEventListener("did-fail-load", onFailed);
    webview.addEventListener("render-process-gone", onGone);
    mount.appendChild(webview);

    return () => {
      webview.removeEventListener("did-fail-load", onFailed);
      webview.removeEventListener("render-process-gone", onGone);
      webview.remove();
    };
  }, [url]);

  useEffect(() => {
    mountRef.current
      ?.querySelector("webview")
      ?.setAttribute("aria-label", title);
  }, [title]);

  return <div ref={mountRef} className="size-full bg-white" />;
}
