import { TypedEventEmitter } from "@posthog/shared";
import { inject, injectable } from "inversify";
import { DEV_FLAGS_SERVICE } from "../../di/tokens";
import { logger } from "../../utils/logger";
import type { DevFlagsService } from "../dev-flags/service";
import {
  DevNetworkEvent,
  type DevNetworkEvents,
  type NetworkRequest,
  type NetworkSim,
} from "./schemas";

const log = logger.scope("dev-network");

const RING_BUFFER_SIZE = 500;

@injectable()
export class DevNetworkService extends TypedEventEmitter<DevNetworkEvents> {
  private requests: NetworkRequest[] = [];
  private nextId = 1;
  private sim: NetworkSim = { offline: false, slowDelayMs: 0 };
  private installed = false;
  private originalFetch: typeof fetch | null = null;
  private wrappedFetch: typeof fetch | null = null;

  constructor(
    @inject(DEV_FLAGS_SERVICE)
    private readonly flags: DevFlagsService,
  ) {
    super();
  }

  install(): void {
    if (this.installed) return;
    this.installed = true;
    this.wrapFetch();
    log.info("Network instrumentation installed");
  }

  // Restore the original `globalThis.fetch` so the instrumentation is fully
  // reversible when developer mode is turned off. Without this the wrapper
  // would linger for the rest of the process even though it stops capturing.
  uninstall(): void {
    if (!this.installed) return;
    this.installed = false;
    if (this.originalFetch && globalThis.fetch === this.wrappedFetch) {
      globalThis.fetch = this.originalFetch;
    }
    this.originalFetch = null;
    this.wrappedFetch = null;
    log.info("Network instrumentation uninstalled");
  }

  private capturing(): boolean {
    return this.installed && this.flags.getFlags().devMode;
  }

  getSnapshot(): NetworkRequest[] {
    return [...this.requests];
  }

  clear(): void {
    this.requests = [];
  }

  getSim(): NetworkSim {
    return { ...this.sim };
  }

  setSim(next: Partial<NetworkSim>): NetworkSim {
    this.sim = { ...this.sim, ...next };
    this.emit(DevNetworkEvent.SimChanged, { ...this.sim });
    return { ...this.sim };
  }

  private record(req: NetworkRequest): void {
    this.requests.push(req);
    if (this.requests.length > RING_BUFFER_SIZE) {
      this.requests.splice(0, this.requests.length - RING_BUFFER_SIZE);
    }
    this.emit(DevNetworkEvent.Request, req);
  }

  recordExternal(req: Omit<NetworkRequest, "id" | "host">): void {
    if (!this.capturing()) return;
    this.record({ ...req, id: this.nextId++, host: safeHost(req.url) });
  }

  private wrapFetch(): void {
    const original = globalThis.fetch;
    if (!original) return;
    this.originalFetch = original;

    const wrapped = async (
      input: RequestInfo | URL,
      init?: RequestInit,
    ): Promise<Response> => {
      if (!this.capturing()) {
        return original(input, init);
      }
      const startedAt = Date.now();
      const start = performance.now();
      const method = (init?.method ?? "GET").toUpperCase();
      const url =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.toString()
            : input.url;
      const host = safeHost(url);
      const id = this.nextId++;

      if (this.sim.offline) {
        const err = new TypeError("Network simulated offline");
        this.record({
          id,
          method,
          url,
          host,
          origin: "main",
          status: null,
          ok: false,
          durationMs: performance.now() - start,
          startedAt,
          bytes: null,
          error: err.message,
        });
        throw err;
      }

      if (this.sim.slowDelayMs > 0) {
        await sleep(this.sim.slowDelayMs);
      }

      try {
        const response = await original(input, init);
        const durationMs = performance.now() - start;
        const bytes = parseContentLength(
          response.headers.get("content-length"),
        );
        this.record({
          id,
          method,
          url,
          host,
          origin: "main",
          status: response.status,
          ok: response.ok,
          durationMs,
          startedAt,
          bytes,
        });
        return response;
      } catch (error) {
        const durationMs = performance.now() - start;
        const message = error instanceof Error ? error.message : String(error);
        this.record({
          id,
          method,
          url,
          host,
          origin: "main",
          status: null,
          ok: false,
          durationMs,
          startedAt,
          bytes: null,
          error: message,
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

    this.wrappedFetch = wrapped as typeof fetch;
    globalThis.fetch = this.wrappedFetch;
  }
}

function safeHost(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return "";
  }
}

function parseContentLength(value: string | null): number | null {
  if (!value) return null;
  const n = Number.parseInt(value, 10);
  return Number.isFinite(n) ? n : null;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
