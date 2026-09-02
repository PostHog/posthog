#!/usr/bin/env node
// Dependency-free static file server for the auto-update feed. Serves a directory
// (latest-mac.yml + zip + blockmap) over HTTP with Range support, which the macOS
// updater needs. Used by the update E2E and for local manual testing.
//
// It also answers the Squirrel.Mac JSON feed that the LEGACY built-in autoUpdater
// expects (what shipped Forge builds run), so the same feed dir drives both the
// new electron-updater client and the old built-in one. See the Forge -> builder
// update E2E (tests/e2e/tests/update-forge.spec.ts).
//
// Usage: node serve.mjs <dir> [port]
import { createReadStream, readFileSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, normalize } from "node:path";

const root = process.argv[2];
const port = Number(process.argv[3] ?? 8080);

if (!root) {
  console.error("Usage: serve.mjs <dir> [port]");
  process.exit(1);
}

const CONTENT_TYPES = {
  ".yml": "text/yaml; charset=utf-8",
  ".yaml": "text/yaml; charset=utf-8",
  ".zip": "application/zip",
  ".blockmap": "application/octet-stream",
  ".json": "application/json; charset=utf-8",
};

// The legacy built-in autoUpdater (Squirrel.Mac) GETs
// /<owner>/<repo>/darwin-<arch>/<currentVersion> and expects 204 when current,
// or 200 + { url } pointing at the zip to install. update.electronjs.org served
// exactly this shape; we reproduce it locally from the feed's latest-mac.yml.
const SQUIRREL_FEED_RE = /\/darwin-(?:arm64|x64)\/([0-9][^/]*)\/?$/;
const PUB_DATE = "2020-01-01T00:00:00Z";

// Read the version + zip the feed offers, staying dependency-free (no YAML lib).
function readFeedMeta() {
  try {
    const yml = readFileSync(join(root, "latest-mac.yml"), "utf8");
    const version = /^version:\s*(.+)$/m.exec(yml)?.[1]?.trim();
    const zip = /(?:url|path):\s*(\S+\.zip)\b/m.exec(yml)?.[1]?.trim();
    if (version && zip) return { version, zip };
  } catch {
    // fall through
  }
  return null;
}

function compareSemver(a, b) {
  const pa = a.split(/[.+-]/).map(Number);
  const pb = b.split(/[.+-]/).map(Number);
  for (let i = 0; i < 3; i++) {
    const diff = (pa[i] || 0) - (pb[i] || 0);
    if (diff) return diff > 0 ? 1 : -1;
  }
  return 0;
}

const server = createServer((req, res) => {
  const urlPath = decodeURIComponent((req.url ?? "/").split("?")[0]);

  const squirrel = SQUIRREL_FEED_RE.exec(urlPath);
  if (squirrel) {
    const meta = readFeedMeta();
    if (!meta) {
      res.writeHead(503);
      res.end("feed metadata missing");
      return;
    }
    const currentVersion = squirrel[1];
    if (compareSemver(meta.version, currentVersion) <= 0) {
      res.writeHead(204);
      res.end();
      return;
    }
    const host = req.headers.host ?? `127.0.0.1:${port}`;
    const body = JSON.stringify({
      url: `http://${host}/${meta.zip}`,
      name: meta.version,
      notes: "",
      pub_date: PUB_DATE,
    });
    res.writeHead(200, {
      "Content-Type": "application/json; charset=utf-8",
      "Content-Length": Buffer.byteLength(body),
    });
    res.end(body);
    return;
  }

  const safePath = normalize(urlPath).replace(/^(\.\.[/\\])+/, "");
  const filePath = join(root, safePath);

  let stat;
  try {
    stat = statSync(filePath);
  } catch {
    res.writeHead(404);
    res.end("Not found");
    return;
  }
  if (!stat.isFile()) {
    res.writeHead(404);
    res.end("Not found");
    return;
  }

  const type = CONTENT_TYPES[extname(filePath)] ?? "application/octet-stream";
  const range = req.headers.range;

  if (range) {
    const match = /bytes=(\d*)-(\d*)/.exec(range);
    let start = 0;
    let end = stat.size - 1;
    if (match?.[1]) {
      start = Number(match[1]);
      if (match[2]) end = Number(match[2]);
    } else if (match?.[2]) {
      // Suffix range (bytes=-N): the last N bytes of the file.
      start = Math.max(0, stat.size - Number(match[2]));
    }
    res.writeHead(206, {
      "Content-Type": type,
      "Content-Range": `bytes ${start}-${end}/${stat.size}`,
      "Accept-Ranges": "bytes",
      "Content-Length": end - start + 1,
    });
    createReadStream(filePath, { start, end }).pipe(res);
    return;
  }

  res.writeHead(200, {
    "Content-Type": type,
    "Content-Length": stat.size,
    "Accept-Ranges": "bytes",
  });
  createReadStream(filePath).pipe(res);
});

server.listen(port, "127.0.0.1", () => {
  console.log(`update feed: http://127.0.0.1:${port} serving ${root}`);
});
