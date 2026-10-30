import type { Task } from "@posthog/shared";
import { Box, Text } from "ink";
import { type ReactElement, useEffect, useMemo, useState } from "react";
import { type CloudRuns, emptyRunView, type RunView } from "../runs";
import { type TranscriptLine, transcriptFrom } from "../transcript";
import { Spinner } from "./Spinner";

const TOOL_COLORS: Record<string, string> = {
  completed: "green",
  failed: "red",
  in_progress: "yellow",
};

function Line({ line }: { line: TranscriptLine }): ReactElement {
  switch (line.kind) {
    case "user":
      return <Text bold>› {line.text}</Text>;
    case "assistant":
      return <Text>{line.text}</Text>;
    case "tool":
      return (
        <Text dimColor wrap="truncate-end">
          <Text color={TOOL_COLORS[line.status] ?? "gray"}>●</Text> {line.title}
        </Text>
      );
    case "notice":
      return (
        <Text
          color={line.tone === "error" ? "red" : undefined}
          dimColor={line.tone === "info"}
        >
          {line.text}
        </Text>
      );
  }
}

function useRunView(runs: CloudRuns, task: Task | undefined): RunView {
  const run = task?.latest_run;
  const cloudRunId = run && run.environment !== "local" ? run.id : null;
  const [view, setView] = useState(emptyRunView);
  useEffect(() => {
    setView(emptyRunView);
    if (!task || !cloudRunId) return;
    return runs.watch(task.id, cloudRunId, setView);
  }, [runs, task?.id, cloudRunId, task]);
  return view;
}

export function Pane({
  title,
  task,
  runs,
  focused,
}: {
  title: string;
  task: Task | undefined;
  runs: CloudRuns;
  focused: boolean;
}): ReactElement {
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
  const run = task?.latest_run;

  let body: ReactElement;
  if (!task) body = <Text dimColor>Open a task from Work.</Text>;
  else if (!run) body = <Text dimColor>This task has no runs yet.</Text>;
  else if (run.environment === "local")
    body = <Text dimColor>Local runs can't be opened here yet.</Text>;
  else if (!view.loaded && !view.error) body = <Spinner label="Loading chat" />;
  else {
    body = (
      <>
        {lines.map((line) => (
          <Line key={line.id} line={line} />
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
        flexGrow={1}
        flexDirection="column"
        justifyContent="flex-end"
        overflow="hidden"
      >
        {body}
      </Box>
    </Box>
  );
}
