/**
 * Stable identity for a run's set of output files. When it changes, a Files box
 * the user collapsed should re-expand so newly produced artifacts are not hidden
 * behind a box dismissed for the previous set. Order-independent by name; the
 * null separator cannot collide with a filename.
 */
export function artifactFilesListKey(
  runId: string | undefined,
  fileNames: readonly string[],
): string {
  return `${runId ?? ""}:${[...fileNames].sort().join("\u0000")}`;
}
