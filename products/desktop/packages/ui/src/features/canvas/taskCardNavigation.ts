export function taskCardNavigation(channelId: string, taskId: string) {
  return {
    to: "/spaces/$channelId/tasks/$taskId" as const,
    params: { channelId, taskId },
  };
}
