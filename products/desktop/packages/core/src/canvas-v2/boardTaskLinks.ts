const boardByTask = new Map<string, string>();
const taskByBoard = new Map<string, string>();

export function linkTaskToBoard(taskId: string, boardId: string): void {
  const previousBoard = boardByTask.get(taskId);
  if (previousBoard !== undefined) taskByBoard.delete(previousBoard);
  const previousTask = taskByBoard.get(boardId);
  if (previousTask !== undefined) boardByTask.delete(previousTask);
  boardByTask.set(taskId, boardId);
  taskByBoard.set(boardId, taskId);
}

export function unlinkTask(taskId: string): void {
  const boardId = boardByTask.get(taskId);
  boardByTask.delete(taskId);
  if (boardId !== undefined && taskByBoard.get(boardId) === taskId) {
    taskByBoard.delete(boardId);
  }
}

export function boardIdForTask(taskId: string): string | undefined {
  return boardByTask.get(taskId);
}

export function taskIdForBoard(boardId: string): string | undefined {
  return taskByBoard.get(boardId);
}
