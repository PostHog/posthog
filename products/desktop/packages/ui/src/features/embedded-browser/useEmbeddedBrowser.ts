import { useHostTRPC } from "@posthog/host-router/react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useSubscription } from "@trpc/tanstack-react-query";
import { useEffect, useRef, useState } from "react";

export interface EmbeddedBrowserPageState {
  viewId: string;
  url: string;
  title: string;
  canGoBack: boolean;
  canGoForward: boolean;
  isLoading: boolean;
}

/**
 * Live page state of one embedded view, seeded by query, kept fresh by the
 * host event stream. `loadError` carries the last main-frame load failure and
 * clears when a new load starts.
 */
export function useEmbeddedBrowserPageState(viewId: string) {
  const trpc = useHostTRPC();
  const [pageState, setPageState] = useState<EmbeddedBrowserPageState | null>(
    null,
  );
  const [loadError, setLoadError] = useState<string | null>(null);

  const { data: initial } = useQuery(
    trpc.embeddedBrowser.getPageState.queryOptions({ viewId }),
  );
  useEffect(() => {
    if (initial) setPageState((prev) => prev ?? initial);
  }, [initial]);

  useSubscription(
    trpc.embeddedBrowser.onEvents.subscriptionOptions(undefined, {
      onData: (event) => {
        if (event.type === "page-state" && event.state.viewId === viewId) {
          if (event.state.isLoading) setLoadError(null);
          setPageState(event.state);
        }
        if (event.type === "load-failed" && event.viewId === viewId) {
          setLoadError(event.errorDescription);
        }
      },
    }),
  );

  return { pageState, loadError };
}

/**
 * Own an embedded view behind a slot element: open it once a URL is chosen
 * and the slot has real bounds, keep the native view glued to the slot's
 * rect, and drive visibility from `visible`. The native view paints ABOVE the
 * renderer, so visibility must come from here — nothing in the DOM can cover
 * it. Inactive panel tabs stay mounted with `visibility: hidden` (their rects
 * stay non-zero), which is exactly why the caller must gate `visible` on the
 * tab being active.
 */
export function useEmbeddedBrowserSlot(input: {
  viewId: string;
  /** null = no URL chosen yet; the view is not created until one is. */
  url: string | null;
  visible: boolean;
}) {
  const { viewId, url, visible } = input;
  const trpc = useHostTRPC();
  const slotRef = useRef<HTMLDivElement | null>(null);
  const openedRef = useRef(false);

  const open = useMutation(trpc.embeddedBrowser.open.mutationOptions());
  const setBounds = useMutation(
    trpc.embeddedBrowser.setBounds.mutationOptions(),
  );
  const setVisible = useMutation(
    trpc.embeddedBrowser.setVisible.mutationOptions(),
  );

  const openMutate = open.mutateAsync;
  const setBoundsMutate = setBounds.mutate;
  const setVisibleMutate = setVisible.mutate;

  // The open URL is only consumed once, at creation; it must NOT re-run the
  // effect. It tracks the persisted current URL as the user browses, and
  // re-running on that would tear down and reopen the live view mid-session.
  const urlRef = useRef(url);
  // Applied after open resolves, so a visibility change that raced the open
  // (user switched tabs while the first load was in flight) still lands.
  const visibleRef = useRef(visible);
  // Mirrored on commit, never during render: React can discard or replay a
  // render, and a value from one that never committed must not leak into the
  // live view. Both are read from async callbacks, which always run later.
  useEffect(() => {
    urlRef.current = url;
    visibleRef.current = visible;
  }, [url, visible]);

  const hasUrl = url != null;

  useEffect(() => {
    const slot = slotRef.current;
    if (!slot || !hasUrl) return;

    let frame: number | null = null;
    let lastRect = "";

    const report = () => {
      frame = null;
      const rect = slot.getBoundingClientRect();
      const bounds = {
        x: Math.round(rect.x),
        y: Math.round(rect.y),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      };
      if (bounds.width === 0 || bounds.height === 0) return;
      const key = JSON.stringify(bounds);
      if (key === lastRect) return;
      lastRect = key;
      if (!openedRef.current) {
        openedRef.current = true;
        const openUrl = urlRef.current;
        if (openUrl == null) return;
        void openMutate({ viewId, url: openUrl, bounds })
          .then(() => {
            setVisibleMutate({ viewId, visible: visibleRef.current });
          })
          .catch(() => {
            openedRef.current = false;
          });
      } else {
        setBoundsMutate({ viewId, bounds });
      }
    };
    const schedule = () => {
      if (frame == null) frame = requestAnimationFrame(report);
    };

    schedule();
    const observer = new ResizeObserver(schedule);
    observer.observe(slot);
    // Layout shifts that move the slot without resizing it (sidebar toggle,
    // panel collapse) resize an ancestor — observing the body catches them.
    observer.observe(document.body);
    window.addEventListener("resize", schedule);

    return () => {
      observer.disconnect();
      window.removeEventListener("resize", schedule);
      if (frame != null) cancelAnimationFrame(frame);
      // Keep the view (and the page in it) alive across task switches; just
      // stop painting over whatever replaces this slot. Actual destruction is
      // owned by useBrowserViewCleanup / task archive.
      setVisibleMutate({ viewId, visible: false });
      openedRef.current = false;
    };
  }, [viewId, hasUrl, openMutate, setBoundsMutate, setVisibleMutate]);

  useEffect(() => {
    if (!openedRef.current) return;
    setVisibleMutate({ viewId, visible });
  }, [visible, viewId, setVisibleMutate]);

  return slotRef;
}
