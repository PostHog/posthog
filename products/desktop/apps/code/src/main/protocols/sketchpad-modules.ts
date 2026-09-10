import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { SKETCHPAD_MODULE_SCHEME } from "@posthog/shared";

let sketchpadDocument: { html: string; csp: string } | null = null;

export function setSketchpadDocument(document: {
  html: string;
  csp: string;
}): void {
  sketchpadDocument = document;
}

import { logger } from "../utils/logger";

const log = logger.scope("sketchpad modules");

interface ModuleEntry {
  sha256: string;
  type: string;
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

export function registerSketchpadModulesProtocol(
  protocolHost: ProtocolHost,
  resourcesDir: string,
): void {
  const dir = join(resourcesDir, "sketchpad-modules");
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

  protocolHost.handle(SKETCHPAD_MODULE_SCHEME, async (request) => {
    if (new URL(request.url).hostname === "sketchpad") {
      if (!sketchpadDocument) return NOT_FOUND();
      return new Response(sketchpadDocument.html, {
        headers: {
          "Content-Type": "text/html; charset=utf-8",
          "Content-Security-Policy": sketchpadDocument.csp,
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
