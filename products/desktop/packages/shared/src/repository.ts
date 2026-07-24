export const parseRepository = (
  repository: string,
): { organization: string; repoName: string } | null => {
  const result = repository.split("/");

  if (result.length !== 2) {
    return null;
  }

  return { organization: result[0], repoName: result[1] };
};

export function getTaskRepository(task: {
  repository?: string | null;
}): string | null {
  return task.repository ?? null;
}
