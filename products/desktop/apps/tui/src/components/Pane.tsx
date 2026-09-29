import type { Task } from "@posthog/shared";
import { Box, Text, useBoxMetrics } from "ink";
import { type ReactElement, useEffect, useMemo, useRef, useState } from "react";
import type { ChatView } from "../chatView";
import { type CloudRuns, emptyRunView, type RunView } from "../runs";
import { transcriptFrom } from "../transcript";
import { Spinner } from "./Spinner";

function useRunView(runs: CloudRuns, task: Task | undefined): RunView {
  const taskId = task?.id;
  const run = task?.latest_run;
  const cloudRunId = run && run.environment !== "local" ? run.id : null;
  const [view, setView] = useState(emptyRunView);
  // Keyed on ids only: each list refresh brings a new task object for the same run.
  useEffect(() => {
    setView(emptyRunView);
    if (!taskId || !cloudRunId) return;
    return runs.watch(taskId, cloudRunId, setView);
  }, [runs, taskId, cloudRunId]);
  return view;
}

export function Pane({
  title,
  task,
  runs,
  chat,
  focused,
}: {
  title: string;
  task: Task | undefined;
  runs: CloudRuns;
  chat: ChatView;
  focused: boolean;
}): ReactElement {
  const body = useRef(null);
  const { width, height } = useBoxMetrics(body);
  const view = useRunView(runs, task);
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
  useEffect(() => chat.setTranscript(lines), [chat, lines]);
  const run = task?.latest_run;

  let content: ReactElement;
  if (!task) content = <Text dimColor>Open a task from Work.</Text>;
  else if (!run) content = <Text dimColor>This task has no runs yet.</Text>;
  else if (run.environment === "local")
    content = <Text dimColor>Local runs can't be opened here yet.</Text>;
  else if (!view.loaded && !view.error)
    content = <Spinner label="Loading chat" />;
  else {
    // pi renders at the pane's measured size; each line is already styled and fitted to the width.
    content = (
      <>
        {(width > 0
          ? chat.render(width, height - (view.error ? 1 : 0))
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
      <Box
        ref={body}
        flexGrow={1}
        flexDirection="column"
        justifyContent="flex-end"
        overflow="hidden"
      >
        {content}
      </Box>
    </Box>
  );
}
