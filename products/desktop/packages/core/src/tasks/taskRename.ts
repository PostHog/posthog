interface TitledTask {
  id: string;
  title: string;
  title_manually_set?: boolean;
}

interface TitledSummary {
  id: string;
  title: string;
}

export function getTaskTitle<T extends TitledTask>(
  tasks: T[] | undefined,
  taskId: string,
): string | undefined {
  return tasks?.find((task) => task.id === taskId)?.title;
}

export function getTaskSummaryTitle<T extends TitledSummary>(
  summaries: T[] | undefined,
  taskId: string,
): string | undefined {
  return summaries?.find((summary) => summary.id === taskId)?.title;
}

export function applyRenameToList<T extends TitledTask>(
  tasks: T[] | undefined,
  taskId: string,
  newTitle: string,
): T[] | undefined {
  return tasks?.map((task) =>
    task.id === taskId
      ? { ...task, title: newTitle, title_manually_set: true }
      : task,
  );
}

export function applyRenameToSummaries<T extends TitledSummary>(
  summaries: T[] | undefined,
  taskId: string,
  newTitle: string,
): T[] | undefined {
  return summaries?.map((summary) =>
    summary.id === taskId ? { ...summary, title: newTitle } : summary,
  );
}

export function applyRenameToDetail<T extends TitledTask>(
  detail: T,
  newTitle: string,
): T {
  return { ...detail, title: newTitle, title_manually_set: true };
}

export function rollbackListData<T extends TitledTask>(
  current: T[] | undefined,
  previous: T[],
  taskId: string,
  newTitle: string,
): T[] {
  if (!current) {
    return previous;
  }
  return getTaskTitle(current, taskId) === newTitle ? previous : current;
}

export function rollbackSummaryData<T extends TitledSummary>(
  current: T[] | undefined,
  previous: T[],
  taskId: string,
  newTitle: string,
): T[] {
  if (!current) {
    return previous;
  }
  return getTaskSummaryTitle(current, taskId) === newTitle ? previous : current;
}

export function rollbackDetailData<T extends TitledTask>(
  current: T | undefined,
  previous: T,
  newTitle: string,
): T {
  if (!current) {
    return previous;
  }
  return current.title === newTitle ? previous : current;
}

export function shouldRollbackSessionTitle(args: {
  detailTitle: string | undefined;
  listTitles: (string | undefined)[];
  newTitle: string;
}): boolean {
  const { detailTitle, listTitles, newTitle } = args;
  return (
    detailTitle === newTitle || listTitles.some((title) => title === newTitle)
  );
}
