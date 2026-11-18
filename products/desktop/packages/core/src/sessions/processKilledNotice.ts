export interface ProcessKilledParams {
  pid: number;
  comm: string;
  treeRssBytes: number;
  memoryCurrentBytes: number;
  memoryLimitBytes: number;
  signal: string;
  at: string;
}

const BYTES_PER_GIB = 1024 ** 3;

function formatGib(bytes: number): string {
  return `${(bytes / BYTES_PER_GIB).toFixed(1)} GiB`;
}

export function formatProcessKilledNotice(params: unknown): string | null {
  const { comm, treeRssBytes, memoryLimitBytes } = (params ?? {}) as Partial<
    Record<keyof ProcessKilledParams, unknown>
  >;
  if (
    typeof comm !== "string" ||
    !comm ||
    typeof treeRssBytes !== "number" ||
    !Number.isFinite(treeRssBytes) ||
    typeof memoryLimitBytes !== "number" ||
    !Number.isFinite(memoryLimitBytes)
  ) {
    return null;
  }
  return `The sandbox stopped ${comm} because it was using ${formatGib(treeRssBytes)} of the ${formatGib(memoryLimitBytes)} available. The agent is still running.`;
}
