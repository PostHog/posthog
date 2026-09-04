import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { CANVAS_V2_MODULE_SCHEME } from "@posthog/shared";

let boardDocument: { html: string; csp: string } | null = null;

export function setCanvasBoardDocument(document: {
  html: string;
  csp: string;
}): void {
  boardDocument = document;
}

import { logger } from "../utils/logger";

const log = logger.scope("canvas modules");

interface ModuleEntry {
  url: string;
  sha256: string;
  type: string;
  bytes: number;
}

interface ModuleManifest {
  version: number;
  files: Record<string, ModuleEntry>;
}

interface ProtocolHost {
  handle(
    scheme: string,
    handler: (request: Request) => Promise<Response>,
  ): void;
}

const SERVABLE_TYPES = new Set([
  "application/javascript",
  "text/javascript",
  "text/css",
  "font/woff2",
  "font/woff",
  "image/svg+xml",
]);

const NOT_FOUND = () => new Response("Not found", { status: 404 });

export function registerCanvasModulesProtocol(
  protocolHost: ProtocolHost,
  resourcesDir: string,
): void {
  const dir = join(resourcesDir, "canvas-modules");
  let manifest: Promise<ModuleManifest | null> | null = null;

  const load = (): Promise<ModuleManifest | null> => {
    manifest ??= readFile(join(dir, "manifest.json"), "utf8")
      .then((text) => JSON.parse(text) as ModuleManifest)
      .catch((error) => {
        log.error("No vendored board modules", { error: String(error) });
        return null;
      });
    return manifest;
  };

  protocolHost.handle(CANVAS_V2_MODULE_SCHEME, async (request) => {
    if (new URL(request.url).hostname === "board") {
      if (!boardDocument) return NOT_FOUND();
      return new Response(boardDocument.html, {
        headers: {
          "Content-Type": "text/html; charset=utf-8",
          "Content-Security-Policy": boardDocument.csp,
          "Cache-Control": "no-store",
          "X-Content-Type-Options": "nosniff",
        },
      });
    }
    const files = (await load())?.files;
    if (!files) return NOT_FOUND();
    const entry = files[keyOf(request.url)];
    if (!entry) {
      log.warn("Refused a board module the lock does not name");
      return NOT_FOUND();
    }
    const body = await readFile(
      join(dir, "blobs", `${entry.sha256}.bin`),
    ).catch(() => null);
    if (!body) return NOT_FOUND();
    if (createHash("sha256").update(body).digest("hex") !== entry.sha256) {
      log.error("A vendored board module does not match the lock");
      return NOT_FOUND();
    }
    const type = SERVABLE_TYPES.has(entry.type)
      ? entry.type
      : "application/octet-stream";
    return new Response(new Uint8Array(body), {
      headers: {
        "Content-Type": `${type}; charset=utf-8`,
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "public, max-age=31536000, immutable",
        "X-Content-Type-Options": "nosniff",
      },
    });
  });
}

export function keyOf(requestUrl: string): string {
  const url = new URL(requestUrl);
  return `${url.hostname}|${url.pathname}${url.search}`;
}
