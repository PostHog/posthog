export function taskCardNavigation(channelId: string, taskId: string) {
  return {
    to: "/website/$channelId/tasks/$taskId" as const,
    params: { channelId, taskId },
  };
}
