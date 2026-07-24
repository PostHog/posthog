export function isObject(value: unknown): value is Record<string, unknown> {
  return !!value && !Array.isArray(value) && typeof value === "object";
}

const asyncIteratorsSupported =
  typeof Symbol === "function" && !!Symbol.asyncIterator;

export function isAsyncIterable<TValue>(
  value: unknown,
): value is AsyncIterable<TValue> {
  return (
    asyncIteratorsSupported && isObject(value) && Symbol.asyncIterator in value
  );
}

/**
 * Takes a value and an async dispose function and returns a new object that implements the AsyncDisposable interface.
 * The returned object is the original value augmented with a Symbol.asyncDispose method.
 * @param thing The value to make async disposable
 * @param dispose Async function to call when disposing the resource
 * @returns The original value with Symbol.asyncDispose method added
 */
export function makeAsyncResource<T>(
  thing: T,
  dispose: () => Promise<void>,
): T & AsyncDisposable {
  const it = thing as T & AsyncDisposable;

  // If Symbol.asyncDispose already exists (e.g., on native async generators),
  // wrap the existing dispose with our custom dispose
  // eslint-disable-next-line no-restricted-syntax
  if (it[Symbol.asyncDispose]) {
    const originalDispose = it[Symbol.asyncDispose].bind(it);
    // eslint-disable-next-line no-restricted-syntax
    it[Symbol.asyncDispose] = async () => {
      await dispose();
      await originalDispose();
    };
    return it;
  }

  // eslint-disable-next-line no-restricted-syntax
  it[Symbol.asyncDispose] = dispose;

  return it;
}

export function iteratorResource<TYield, TReturn, TNext>(
  iterable: AsyncIterable<TYield, TReturn, TNext>,
): AsyncIterator<TYield, TReturn, TNext> & AsyncDisposable {
  const iterator = iterable[Symbol.asyncIterator]();

  return makeAsyncResource(iterator, async () => {
    await iterator.return?.();
  });
}

/**
 * Run an IIFE
 */
export const run = <TValue>(fn: () => TValue): TValue => fn();
