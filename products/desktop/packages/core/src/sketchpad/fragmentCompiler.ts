export function createFragmentCompiler<T>(
  load: (refs: string[]) => Promise<Record<string, T>>,
): (ref: string) => Promise<T> {
  const pending = new Map<
    string,
    {
      promise: Promise<T>;
      resolve: (value: T) => void;
      reject: (error: unknown) => void;
      deadline: number;
    }
  >();
  let loading = false;
  const flush = async (): Promise<void> => {
    while (pending.size) {
      const batch = [];
      for (const entry of pending) {
        batch.push(entry);
        if (batch.length === 256) break;
      }
      let completed = 0;
      try {
        const results = await load(batch.map(([ref]) => ref));
        for (const [ref, request] of batch) {
          if (results[ref] !== undefined) request.resolve(results[ref]);
          else if (Date.now() >= request.deadline)
            request.reject(
              new Error(
                "Fragment compilation timed out. Open the board again.",
              ),
            );
          else continue;
          pending.delete(ref);
          completed++;
        }
      } catch (error) {
        for (const [ref, request] of batch) {
          request.reject(error);
          pending.delete(ref);
        }
        completed = batch.length;
      }
      if (!completed) await new Promise((resolve) => setTimeout(resolve, 250));
    }
    loading = false;
  };
  return (ref) => {
    const existing = pending.get(ref);
    if (existing) return existing.promise;
    let resolve!: (value: T) => void;
    let reject!: (error: unknown) => void;
    const promise = new Promise<T>((accept, fail) => {
      resolve = accept;
      reject = fail;
    });
    pending.set(ref, {
      promise,
      resolve,
      reject,
      deadline: Date.now() + 150_000,
    });
    if (!loading) {
      loading = true;
      queueMicrotask(() => void flush());
    }
    return promise;
  };
}
