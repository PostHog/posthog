/**
 * Races an operation against a timeout.
 * Returns success with the value if the operation completes in time,
 * or timeout if the operation takes longer than the specified duration.
 */
export async function withTimeout<T>(
  operation: Promise<T>,
  timeoutMs: number,
): Promise<{ result: "success"; value: T } | { result: "timeout" }> {
  let timeoutHandle!: ReturnType<typeof setTimeout>;
  const timeoutPromise = new Promise<{ result: "timeout" }>((resolve) => {
    timeoutHandle = setTimeout(() => resolve({ result: "timeout" }), timeoutMs);
  });
  const operationPromise = operation.then((value) => ({
    result: "success" as const,
    value,
  }));
  try {
    return await Promise.race([operationPromise, timeoutPromise]);
  } finally {
    clearTimeout(timeoutHandle);
  }
}
