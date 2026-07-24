import os from "node:os";
import { OTLPLogExporter } from "@opentelemetry/exporter-logs-otlp-http";
import { resourceFromAttributes } from "@opentelemetry/resources";
import {
  BatchLogRecordProcessor,
  LoggerProvider,
} from "@opentelemetry/sdk-logs";
import { ATTR_SERVICE_NAME } from "@opentelemetry/semantic-conventions";
import type ElectronLog from "electron-log";
import { getAppVersion } from "./env";

/** Maps electron-log levels to OTEL severity text. Most are just uppercase,
 *  but "verbose" and "silly" need explicit mapping. */
const SEVERITY_TEXT: Record<string, string> = {
  verbose: "DEBUG",
  silly: "TRACE",
};

let loggerProvider: LoggerProvider | null = null;

function formatBody(data: unknown[]): string {
  return data
    .map((item) => {
      if (typeof item === "string") return item;
      if (item instanceof Error) return `${item.message}\n${item.stack ?? ""}`;
      try {
        return JSON.stringify(item);
      } catch {
        return String(item);
      }
    })
    .join(" ");
}

export function initOtelTransport(
  level: ElectronLog.LevelOption,
): ElectronLog.Transport {
  const apiKey = process.env.VITE_POSTHOG_API_KEY;
  const apiHost = process.env.VITE_POSTHOG_API_HOST;

  const noop: ElectronLog.Transport = Object.assign(
    (_message: ElectronLog.LogMessage) => {},
    { level: false as const, transforms: [] as ElectronLog.TransformFn[] },
  );

  if (!apiKey || !apiHost) {
    return noop;
  }

  const url = `${apiHost}/i/v1/logs`;
  try {
    new URL(url);
  } catch {
    return noop;
  }

  const exporter = new OTLPLogExporter({
    url,
    headers: { Authorization: `Bearer ${apiKey}` },
  });

  const processor = new BatchLogRecordProcessor(exporter, {
    scheduledDelayMillis: 2000,
  });

  loggerProvider = new LoggerProvider({
    resource: resourceFromAttributes({
      [ATTR_SERVICE_NAME]: "posthog-code-desktop",
      "service.version": getAppVersion(),
      "os.type": process.platform,
      "os.version": os.release(),
      "process.runtime.name": "electron",
      "process.runtime.version": process.versions.electron,
    }),
    processors: [processor],
  });

  const otelLogger = loggerProvider.getLogger("electron-main");

  const transport = ((message: ElectronLog.LogMessage) => {
    const levelStr = message.level ?? "info";
    const severityText = SEVERITY_TEXT[levelStr] ?? levelStr.toUpperCase();

    otelLogger.emit({
      severityText,
      body: formatBody(message.data),
      attributes: {
        ...(message.scope ? { "log.scope": message.scope } : {}),
      },
    });
  }) as ElectronLog.Transport;

  transport.level = level;
  transport.transforms = [];

  return transport;
}

export async function shutdownOtelTransport(): Promise<void> {
  if (loggerProvider) {
    await loggerProvider.forceFlush();
    await loggerProvider.shutdown();
    loggerProvider = null;
  }
}
