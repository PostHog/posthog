export function isSignalReportTaskCapError(error: unknown): boolean {
  const message =
    typeof error === "string"
      ? error
      : error instanceof Error
        ? error.message
        : JSON.stringify(error);

  return message?.includes('"code":"signal_report_task_cap"') ?? false;
}
