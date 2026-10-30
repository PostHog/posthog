import type { Task } from "@posthog/shared";
import { Box, Text, useBoxMetrics } from "ink";
import { type ReactElement, useEffect, useMemo, useRef, useState } from "react";
import type { ChatView } from "../chatView";
import type { Composer } from "../composer";
import {
  type CloudRuns,
  emptyRunView,
  type RunSubscription,
  type RunView,
} from "../runs";
import { transcriptFrom } from "../transcript";
import { Spinner } from "./Spinner";

function useRunView(
  runs: CloudRuns,
  task: Task | undefined,
): { view: RunView; loadOlder: () => void } {
  const taskId = task?.id;
  const run = task?.latest_run;
  const cloudRunId = run && run.environment !== "local" ? run.id : null;
  const [view, setView] = useState(emptyRunView);
  const subscription = useRef<RunSubscription | null>(null);
  // Keyed on ids only: each list refresh brings a new task object for the same run.
  useEffect(() => {
    setView(emptyRunView);
    if (!taskId || !cloudRunId) return;
    const current = runs.watch(taskId, cloudRunId, setView);
    subscription.current = current;
    return () => {
      subscription.current = null;
      current.stop();
    };
  }, [runs, taskId, cloudRunId]);
  return { view, loadOlder: () => void subscription.current?.loadOlder() };
}

export function Pane({
  title,
  task,
  runs,
  chat,
  composer,
  focused,
}: {
  title: string;
  task: Task | undefined;
  runs: CloudRuns;
  chat: ChatView;
  composer: Composer;
  focused: boolean;
}): ReactElement {
  const body = useRef(null);
  const { width, height } = useBoxMetrics(body);
  const { view, loadOlder } = useRunView(runs, task);
  const lines = useMemo(
    () =>
      task
        ? transcriptFrom(
            task.runtime,
            view.entries,
            task.description || task.description_preview,
          )
        : [],
    [task, view.entries],
  );
  const hasOlder = view.windowStart > 0;
  // Set before this render draws the chat, so a frame never shows the previous transcript.
  const shown = useRef<{
    chat: ChatView;
    lines: typeof lines;
    hasOlder: boolean;
  } | null>(null);
  if (
    shown.current?.chat !== chat ||
    shown.current.lines !== lines ||
    shown.current.hasOlder !== hasOlder
  ) {
    chat.setTranscript(lines, { hasOlder });
    shown.current = { chat, lines, hasOlder };
  }
  // Reaching the top, or a transcript shorter than the pane, pulls in the page above.
  useEffect(() => {
    if (width > 0 && hasOlder && !view.loadingOlder && chat.isAtTop())
      loadOlder();
  });
  const run = task?.latest_run;

  const composerLines = width > 0 ? composer.render(width, focused) : [];
  const chatHeight = height - composerLines.length - (view.error ? 1 : 0);

  let content: ReactElement;
  if (!task)
    content = <Text dimColor>Type a message to start a cloud run.</Text>;
  else if (!run) content = <Text dimColor>This task has no runs yet.</Text>;
  else if (run.environment === "local")
    content = <Text dimColor>Local runs can't be opened here yet.</Text>;
  else if (!view.loaded && !view.error)
    content = <Spinner label="Loading chat" />;
  else {
    // pi renders at the pane's measured size; each line is already styled and fitted to the width.
    content = (
      <>
        {(width > 0 && chatHeight > 0
          ? chat.render(width, chatHeight)
          : []
        ).map((line, index) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: rows are positions on screen
          <Text key={index} wrap="truncate-end">
            {line}
          </Text>
        ))}
        {view.error && <Text color="red">{view.error}</Text>}
      </>
    );
  }

  return (
    <Box flexGrow={1} flexDirection="column" paddingX={1} overflow="hidden">
      <Text bold={focused} dimColor={!focused} wrap="truncate-end">
        {title}
      </Text>
      <Box ref={body} flexGrow={1} flexDirection="column" overflow="hidden">
        <Box
          flexGrow={1}
          flexDirection="column"
          justifyContent="flex-end"
          overflow="hidden"
        >
          {content}
        </Box>
        {composerLines.map((line, index) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: rows are positions on screen
          <Text key={`composer-${index}`} wrap="truncate-end">
            {line}
          </Text>
        ))}
      </Box>
    </Box>
  );
}
