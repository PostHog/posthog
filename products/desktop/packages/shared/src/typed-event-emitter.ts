type AnyListener = (payload: unknown) => void;

interface ListenerRecord {
  fn: AnyListener;
  original: AnyListener;
  once: boolean;
}

/**
 * Browser-safe, dependency-free EventEmitter with a typed event map and an
 * async-iterable bridge. Drop-in for the node:events-based emitter used across
 * the main process and workspace-server, but importable from packages/core
 * (and therefore web/mobile hosts) because it touches no Node builtins.
 *
 * `toIterable` buffers events that arrive between iterations so a slow consumer
 * never silently drops events — matching node:events `on()` semantics that the
 * tRPC subscription routers depend on.
 */
export class TypedEventEmitter<TEvents> {
  private readonly registry = new Map<string, ListenerRecord[]>();
  private maxListeners = 50;

  private add(
    event: string,
    original: AnyListener,
    fn: AnyListener,
    once: boolean,
    prepend: boolean,
  ): this {
    let records = this.registry.get(event);
    if (!records) {
      records = [];
      this.registry.set(event, records);
    }
    const record: ListenerRecord = { fn, original, once };
    if (prepend) {
      records.unshift(record);
    } else {
      records.push(record);
    }
    return this;
  }

  on<K extends keyof TEvents & string>(
    event: K,
    listener: (payload: TEvents[K]) => void,
  ): this {
    return this.add(
      event,
      listener as AnyListener,
      listener as AnyListener,
      false,
      false,
    );
  }

  addListener<K extends keyof TEvents & string>(
    event: K,
    listener: (payload: TEvents[K]) => void,
  ): this {
    return this.on(event, listener);
  }

  prependListener<K extends keyof TEvents & string>(
    event: K,
    listener: (payload: TEvents[K]) => void,
  ): this {
    return this.add(
      event,
      listener as AnyListener,
      listener as AnyListener,
      false,
      true,
    );
  }

  private addOnce<K extends keyof TEvents & string>(
    event: K,
    listener: (payload: TEvents[K]) => void,
    prepend: boolean,
  ): this {
    const original = listener as AnyListener;
    const wrapper: AnyListener = (payload) => {
      this.removeRecord(event, original, true);
      original(payload);
    };
    return this.add(event, original, wrapper, true, prepend);
  }

  once<K extends keyof TEvents & string>(
    event: K,
    listener: (payload: TEvents[K]) => void,
  ): this {
    return this.addOnce(event, listener, false);
  }

  prependOnceListener<K extends keyof TEvents & string>(
    event: K,
    listener: (payload: TEvents[K]) => void,
  ): this {
    return this.addOnce(event, listener, true);
  }

  private removeRecord(
    event: string,
    original: AnyListener,
    onlyOnce: boolean,
  ): void {
    const records = this.registry.get(event);
    if (!records) {
      return;
    }
    for (let i = records.length - 1; i >= 0; i--) {
      const record = records[i];
      if (record.original === original && (!onlyOnce || record.once)) {
        records.splice(i, 1);
        break;
      }
    }
    if (records.length === 0) {
      this.registry.delete(event);
    }
  }

  off<K extends keyof TEvents & string>(
    event: K,
    listener: (payload: TEvents[K]) => void,
  ): this {
    this.removeRecord(event, listener as AnyListener, false);
    return this;
  }

  removeListener<K extends keyof TEvents & string>(
    event: K,
    listener: (payload: TEvents[K]) => void,
  ): this {
    return this.off(event, listener);
  }

  removeAllListeners<K extends keyof TEvents & string>(event?: K): this {
    if (event === undefined) {
      this.registry.clear();
    } else {
      this.registry.delete(event);
    }
    return this;
  }

  emit<K extends keyof TEvents & string>(
    event: K,
    payload: TEvents[K],
  ): boolean {
    const records = this.registry.get(event);
    if (!records || records.length === 0) {
      return false;
    }
    for (const record of [...records]) {
      // An `async` listener returns a promise; if it rejects (or throws
      // synchronously before its first await) the rejection would otherwise
      // escape this fire-and-forget call and surface as an unhandled rejection.
      // Swallow it here so one misbehaving listener can never crash the process
      // or pollute error tracking — listeners that care must handle their own
      // errors.
      const result = record.fn(payload) as unknown;
      if (
        result != null &&
        typeof (result as { then?: unknown }).then === "function"
      ) {
        (result as Promise<unknown>).then(undefined, () => {});
      }
    }
    return true;
  }

  listeners<K extends keyof TEvents & string>(
    event: K,
  ): ((payload: TEvents[K]) => void)[] {
    return (this.registry.get(event) ?? []).map(
      (record) => record.original as (payload: TEvents[K]) => void,
    );
  }

  rawListeners<K extends keyof TEvents & string>(
    event: K,
  ): ((payload: TEvents[K]) => void)[] {
    return (this.registry.get(event) ?? []).map(
      (record) => record.fn as (payload: TEvents[K]) => void,
    );
  }

  listenerCount<K extends keyof TEvents & string>(event: K): number {
    return this.registry.get(event)?.length ?? 0;
  }

  eventNames(): (keyof TEvents & string)[] {
    return [...this.registry.keys()] as (keyof TEvents & string)[];
  }

  setMaxListeners(max: number): this {
    this.maxListeners = max;
    return this;
  }

  getMaxListeners(): number {
    return this.maxListeners;
  }

  async *toIterable<K extends keyof TEvents & string>(
    event: K,
    opts?: { signal?: AbortSignal },
  ): AsyncIterableIterator<TEvents[K]> {
    const signal = opts?.signal;
    if (signal?.aborted) {
      return;
    }

    const queue: TEvents[K][] = [];
    let pending: ((result: IteratorResult<TEvents[K]>) => void) | null = null;
    let ended = false;

    const listener = (payload: TEvents[K]) => {
      if (pending) {
        const resolve = pending;
        pending = null;
        resolve({ value: payload, done: false });
      } else {
        queue.push(payload);
      }
    };

    const end = () => {
      ended = true;
      if (pending) {
        const resolve = pending;
        pending = null;
        resolve({ value: undefined as never, done: true });
      }
    };

    this.on(event, listener);
    signal?.addEventListener("abort", end, { once: true });

    try {
      while (true) {
        if (queue.length > 0) {
          yield queue.shift() as TEvents[K];
          continue;
        }
        if (ended) {
          return;
        }
        const result = await new Promise<IteratorResult<TEvents[K]>>(
          (resolve) => {
            pending = resolve;
          },
        );
        if (result.done) {
          return;
        }
        yield result.value;
      }
    } finally {
      this.off(event, listener);
      signal?.removeEventListener("abort", end);
    }
  }
}
