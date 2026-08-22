export function taskCardNavigation(channelId: string, taskId: string) {
  return {
    to: "/tasks/$taskId" as const,
    params: { channelId, taskId },
  };
}
