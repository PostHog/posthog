import type { DevNetworkService } from "../services/dev-network/service";
import { parseContentLength, recordNetworkRequest } from "./network-log";

interface WebRequestFilter {
  urls: string[];
}

interface RequestDetails {
  id: number;
  method: string;
  url: string;
  timestamp: number;
}

interface CompletedDetails extends RequestDetails {
  statusCode: number;
  responseHeaders?: Record<string, string[]>;
}

interface FailedDetails extends RequestDetails {
  error: string;
}

export interface ObservableWebRequest {
  onSendHeaders(
    filter: WebRequestFilter,
    listener: (details: RequestDetails) => void,
  ): void;
  onCompleted(
    filter: WebRequestFilter,
    listener: (details: CompletedDetails) => void,
  ): void;
  onErrorOccurred(
    filter: WebRequestFilter,
    listener: (details: FailedDetails) => void,
  ): void;
}

interface PendingRequest {
  startedAt: number;
}

const MAX_PENDING_REQUESTS = 2000;
const pending = new Map<number, PendingRequest>();

function trackPending(id: number, startedAt: number): void {
  if (pending.size >= MAX_PENDING_REQUESTS) {
    const oldest = pending.keys().next().value;
    if (oldest !== undefined) pending.delete(oldest);
  }
  pending.set(id, { startedAt });
}

function takeDuration(id: number, endedAt: number): number {
  const start = pending.get(id);
  pending.delete(id);
  return start ? endedAt - start.startedAt : 0;
}

export function contentLengthFromHeaders(
  headers?: Record<string, string[]>,
): number | null {
  if (!headers) return null;
  const header = Object.entries(headers).find(
    ([name]) => name.toLowerCase() === "content-length",
  );
  return parseContentLength(header?.[1]?.[0]);
}

let installed = false;

export function installRendererNetworkLogging(
  webRequest: ObservableWebRequest,
  devNetwork: DevNetworkService,
): void {
  if (installed) return;
  installed = true;

  const filter: WebRequestFilter = { urls: ["http://*/*", "https://*/*"] };

  webRequest.onSendHeaders(filter, (details) => {
    trackPending(details.id, details.timestamp);
  });

  webRequest.onCompleted(filter, (details) => {
    const durationMs = takeDuration(details.id, details.timestamp);
    const bytes = contentLengthFromHeaders(details.responseHeaders);
    recordNetworkRequest({
      origin: "renderer",
      method: details.method,
      url: details.url,
      status: details.statusCode,
      durationMs,
      bytes,
    });
    devNetwork.recordExternal({
      origin: "renderer",
      method: details.method,
      url: details.url,
      status: details.statusCode,
      ok: details.statusCode >= 200 && details.statusCode < 300,
      durationMs,
      startedAt: details.timestamp - durationMs,
      bytes,
    });
  });

  webRequest.onErrorOccurred(filter, (details) => {
    const durationMs = takeDuration(details.id, details.timestamp);
    recordNetworkRequest({
      origin: "renderer",
      method: details.method,
      url: details.url,
      status: null,
      durationMs,
      bytes: null,
      error: details.error,
    });
    devNetwork.recordExternal({
      origin: "renderer",
      method: details.method,
      url: details.url,
      status: null,
      ok: false,
      durationMs,
      startedAt: details.timestamp - durationMs,
      bytes: null,
      error: details.error,
    });
  });
}
