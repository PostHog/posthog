export interface LoaderState<T> {
  items: T[];
  loading: boolean;
}

export interface SuggestionLoaderConfig<T> {
  items: (query: string) => T[] | Promise<T[]>;
  debounceMs?: number;
}

export interface SuggestionLoader<T> {
  load: (query: string) => T[];
  subscribe: (fn: (state: LoaderState<T>) => void) => () => void;
  reset: () => void;
  getState: () => LoaderState<T>;
}

export function createSuggestionLoader<T>(
  config: SuggestionLoaderConfig<T>,
): SuggestionLoader<T> {
  const { items: loadItems, debounceMs = 0 } = config;

  let cachedItems: T[] = [];
  let loading = false;
  let queryCounter = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;
  const subscribers = new Set<(state: LoaderState<T>) => void>();

  const publish = () => {
    const snapshot: LoaderState<T> = { items: cachedItems, loading };
    for (const fn of subscribers) fn(snapshot);
  };

  const clearTimer = () => {
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
  };

  const runAsync = (id: number, promise: Promise<T[]>) => {
    loading = true;
    publish();
    promise.then((results) => {
      if (id !== queryCounter) return;
      cachedItems = results;
      loading = false;
      publish();
    });
  };

  return {
    load(query) {
      const id = ++queryCounter;
      clearTimer();

      if (debounceMs > 0) {
        loading = true;
        publish();
        timer = setTimeout(() => {
          runAsync(id, Promise.resolve(loadItems(query)));
        }, debounceMs);
        return cachedItems;
      }

      const result = loadItems(query);
      if (!(result instanceof Promise)) {
        cachedItems = result;
        loading = false;
        publish();
        return cachedItems;
      }

      runAsync(id, result);
      return cachedItems;
    },

    subscribe(fn) {
      subscribers.add(fn);
      return () => {
        subscribers.delete(fn);
      };
    },

    reset() {
      queryCounter++;
      clearTimer();
      cachedItems = [];
      loading = false;
      publish();
    },

    getState() {
      return { items: cachedItems, loading };
    },
  };
}
