/** Maps `items` through `mapper` with at most `concurrency` in flight, preserving
 * input order. Stops early if `options.signal` aborts. */
export async function mapWithConcurrency<T, R>(
  items: readonly T[],
  concurrency: number,
  mapper: (item: T) => Promise<R>,
  options?: { signal?: AbortSignal },
): Promise<R[]> {
  if (items.length === 0) return [];
  const results = new Array<R>(items.length);
  let index = 0;
  const worker = async () => {
    while (index < items.length) {
      if (options?.signal?.aborted) return;
      const i = index++;
      results[i] = await mapper(items[i]);
    }
  };
  await Promise.all(
    Array.from({ length: Math.min(concurrency, items.length) }, () => worker()),
  );
  return results;
}
