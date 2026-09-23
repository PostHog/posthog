import { WorkerPoolContextProvider } from "@pierre/diffs/react";
import { useService } from "@posthog/di/react";
import { DIFFS_HIGHLIGHTER_OPTIONS } from "@posthog/ui/features/sessions/diffHighlighterOptions";
import {
  DIFF_WORKER_FACTORY,
  type DiffWorkerFactory,
} from "@posthog/ui/shell/diffWorkerHost";
import { type ReactElement, type ReactNode, useMemo } from "react";

export function DiffWorkerPool({
  children,
}: {
  children: ReactNode;
}): ReactElement {
  const workerFactory = useService<DiffWorkerFactory>(DIFF_WORKER_FACTORY);
  // The library shares one pool per renderer; every caller must use the same budget.
  const poolOptions = useMemo(
    () => ({ workerFactory, poolSize: 2, totalASTLRUCacheSize: 200 }),
    [workerFactory],
  );

  return (
    <WorkerPoolContextProvider
      poolOptions={poolOptions}
      highlighterOptions={DIFFS_HIGHLIGHTER_OPTIONS}
    >
      {children}
    </WorkerPoolContextProvider>
  );
}
