export interface MemorySnapshot {
  totalWorkingSetKb: number;
  peakWorkingSetKb: number;
  processCount: number;
  byType: Record<string, number>;
}

export function collectMemorySnapshot(
  getMetrics: () => Electron.ProcessMetric[],
): MemorySnapshot | undefined {
  try {
    const metrics = getMetrics();
    let totalWorkingSetKb = 0;
    let peakWorkingSetKb = 0;
    const byType: Record<string, number> = {};
    for (const metric of metrics) {
      const workingSet = metric.memory.workingSetSize;
      totalWorkingSetKb += workingSet;
      peakWorkingSetKb = Math.max(
        peakWorkingSetKb,
        metric.memory.peakWorkingSetSize,
      );
      byType[metric.type] = (byType[metric.type] ?? 0) + workingSet;
    }
    return {
      totalWorkingSetKb,
      peakWorkingSetKb,
      processCount: metrics.length,
      byType,
    };
  } catch {
    return undefined;
  }
}

export function flattenMemorySnapshot(
  memory: MemorySnapshot | undefined,
): Record<string, number | string> {
  if (!memory) {
    return {};
  }
  return {
    memoryTotalWorkingSetKb: memory.totalWorkingSetKb,
    memoryPeakWorkingSetKb: memory.peakWorkingSetKb,
    memoryProcessCount: memory.processCount,
    memoryByType: JSON.stringify(memory.byType),
  };
}
