import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import {
  buildSketchpadFrameDocument,
  sketchpadFramePolicy,
} from "@posthog/core/sketchpad/frameDocument";
import { SKETCHPAD_MODULE_SCHEME, sketchpadModuleKey } from "@posthog/shared";
import { logger } from "../utils/logger";

const FRAME_DOCUMENT = buildSketchpadFrameDocument({ vendoredModules: true });
const FRAME_POLICY = sketchpadFramePolicy(true);

function serveFrameDocument(): Response {
  return new Response(FRAME_DOCUMENT, {
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Content-Security-Policy": FRAME_POLICY,
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

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
        manifest = null;
        log.error("No vendored sketchpad modules", { error: String(error) });
        return null;
      });
    return manifest;
  };

  const serveVendoredModule = async (request: Request): Promise<Response> => {
    const files = (await load())?.files;
    if (!files) return NOT_FOUND();
    const entry = files[sketchpadModuleKey(request.url)];
    if (!entry) {
      log.warn("Refused a sketchpad module the lock does not name");
      return NOT_FOUND();
    }
    const body = await readFile(
      join(dir, "blobs", `${entry.sha256}.bin`),
    ).catch(() => null);
    if (!body) return NOT_FOUND();
    if (createHash("sha256").update(body).digest("hex") !== entry.sha256) {
      log.error("A vendored sketchpad module does not match the lock");
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
  };
  protocolHost.handle(SKETCHPAD_MODULE_SCHEME, async (request) =>
    new URL(request.url).hostname === "sketchpad"
      ? serveFrameDocument()
      : serveVendoredModule(request),
  );
}
