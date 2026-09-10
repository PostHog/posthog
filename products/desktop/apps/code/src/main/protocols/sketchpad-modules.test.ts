import { createHash } from "node:crypto";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { SKETCHPAD_URL, vendoredModuleUrl } from "@posthog/shared";
import { expect, it } from "vitest";
import { registerSketchpadModulesProtocol } from "./sketchpad-modules";

it("serves the host document without registration and retries a missing module manifest", async () => {
  const resources = await mkdtemp(join(tmpdir(), "sketchpad-modules-"));
  let serve!: (request: Request) => Promise<Response>;
  registerSketchpadModulesProtocol(
    {
      handle: (_scheme, handler) => {
        serve = handler;
      },
    },
    resources,
  );
  try {
    const document = await serve(new Request(SKETCHPAD_URL));
    expect(document.status).toBe(200);
    expect(document.headers.get("Content-Security-Policy")).toContain(
      "connect-src 'none'",
    );
    expect(await document.text()).toContain("posthog-sketchpad://esm");
    const request = new Request(vendoredModuleUrl("https://esm.sh/test?v=1"));
    expect((await serve(request)).status).toBe(404);
    const dir = join(resources, "sketchpad-modules");
    await mkdir(join(dir, "blobs"), { recursive: true });
    const body = "export const value = 1;";
    const sha256 = createHash("sha256").update(body).digest("hex");
    await writeFile(
      join(dir, "manifest.json"),
      JSON.stringify({
        version: 1,
        files: { "esm|/test?v=1": { sha256, type: "application/javascript" } },
      }),
    );
    await writeFile(join(dir, "blobs", `${sha256}.bin`), body);
    const module = await serve(request);
    expect(module.status).toBe(200);
    expect(await module.text()).toBe(body);
    await writeFile(join(dir, "blobs", `${sha256}.bin`), "changed");
    expect((await serve(request)).status).toBe(404);
  } finally {
    await rm(resources, { recursive: true, force: true });
  }
});
