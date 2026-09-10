import { parseContentLength, recordNetworkRequest } from "./network-log";

export function createNetworkLoggingFetch(
  original: typeof fetch,
): typeof fetch {
  const wrapped = async (
    input: RequestInfo | URL,
    init?: RequestInit,
  ): Promise<Response> => {
    const method = (
      init?.method ?? (input instanceof Request ? input.method : "GET")
    ).toUpperCase();
    const url =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.toString()
          : input.url;
    const start = performance.now();

    try {
      const response = await original(input, init);
      recordNetworkRequest({
        origin: "main",
        method,
        url,
        status: response.status,
        durationMs: performance.now() - start,
        bytes: parseContentLength(response.headers.get("content-length")),
      });
      return response;
    } catch (error) {
      recordNetworkRequest({
        origin: "main",
        method,
        url,
        status: null,
        durationMs: performance.now() - start,
        bytes: null,
        error:
          error instanceof Error
            ? `${error.name}: ${error.message}`
            : String(error),
      });
      throw error;
    }
  };

  const preconnect = (
    original as unknown as {
      preconnect?: (...args: unknown[]) => unknown;
    }
  ).preconnect;
  Object.defineProperty(wrapped, "preconnect", {
    value: preconnect?.bind(original) ?? (() => undefined),
  });

  return wrapped as typeof fetch;
}

let installed = false;

export function installMainFetchLogging(): void {
  if (installed) return;
  installed = true;
  const original = globalThis.fetch;
  if (!original) return;
  globalThis.fetch = createNetworkLoggingFetch(original);
}
