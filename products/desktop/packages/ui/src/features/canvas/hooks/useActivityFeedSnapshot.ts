import {
  type CanvasActivityFeedSnapshot,
  type FeedCanvasLike,
  type FeedReportLike,
  toCanvasActivityFeed,
} from "@posthog/core/canvas/canvasActivityFeed";
import { humanizeReportTitle } from "@posthog/core/inbox/reportPresentation";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useAllCanvases } from "@posthog/ui/features/canvas/hooks/useDashboards";
import { useInboxActivityPreview } from "@posthog/ui/features/canvas/hooks/useInboxActivityPreview";
import { useTaskActivity } from "@posthog/ui/features/canvas/hooks/useTaskActivity";
import { useCallback, useMemo, useRef } from "react";

/**
 * Reads the same three sources the Activity page reads, and returns the
 * snapshot a canvas gets from `ph.activityFeed()`.
 *
 * The reader is a callback over a ref rather than the value itself, because a
 * canvas asks whenever it wants: the request must see the newest poll, and a
 * value in the dependency list would rebuild the data bridge on every poll and
 * remount the frame.
 */
export function useActivityFeedSnapshot(): (
  limit?: number,
) => CanvasActivityFeedSnapshot {
  const taskActivity = useTaskActivity();
  // The person's own Self-driving filters decide these, and the preview caps
  // them, so a canvas sees what the built page would show rather than the
  // whole inbox.
  const inboxActivity = useInboxActivityPreview();
  const { dashboards } = useAllCanvases();
  const { channels } = useChannels();

  const spaceNames = useMemo(
    () => new Map(channels.map((channel) => [channel.id, channel.name])),
    [channels],
  );

  const canvases: FeedCanvasLike[] = useMemo(
    () =>
      dashboards.map((record) => ({
        id: record.id,
        name: record.name,
        updatedAt: record.updatedAt,
        spaceName: spaceNames.get(record.channelId) ?? null,
      })),
    [dashboards, spaceNames],
  );

  const reports: FeedReportLike[] = useMemo(
    () =>
      inboxActivity.reports.map((report) => ({
        id: report.id,
        // The same title the built feed row shows, so the two pages name a
        // report the same way.
        title: humanizeReportTitle(report.title, "Untitled report"),
        summary: report.summary ?? null,
        createdAt: report.updated_at,
      })),
    [inboxActivity.reports],
  );

  const latest = useRef({ taskItems: taskActivity.items, canvases, reports });
  latest.current = { taskItems: taskActivity.items, canvases, reports };

  return useCallback(
    (limit?: number) => toCanvasActivityFeed({ ...latest.current, limit }),
    [],
  );
}
