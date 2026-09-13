import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { describe, expect, it } from "vitest";
import { createPiContextWikiExtension } from "./context-wiki-extension";

type BeforeAgentStartHandler = (event: {
  systemPrompt: string;
}) => Promise<{ systemPrompt?: string }>;

async function runHandler(
  mountPath: string | undefined,
): Promise<{ systemPrompt?: string }> {
  let handler: BeforeAgentStartHandler | undefined;
  const extension = createPiContextWikiExtension(mountPath);
  await (extension.factory as (pi: ExtensionAPI) => void)({
    on: (event: string, registered: BeforeAgentStartHandler) => {
      if (event === "before_agent_start") {
        handler = registered;
      }
    },
  } as unknown as ExtensionAPI);
  if (!handler) {
    throw new Error("before_agent_start handler was not registered");
  }
  return handler({ systemPrompt: "Base prompt." });
}

describe("createPiContextWikiExtension", () => {
  it("appends wiki instructions when the mount exists", async () => {
    const mount = fs.mkdtempSync(path.join(os.tmpdir(), "context-wiki-"));

    const result = await runHandler(mount);

    expect(result.systemPrompt).toContain("Base prompt.");
    expect(result.systemPrompt).toContain("# Context Wiki");
    expect(result.systemPrompt).toContain(mount);
  });

  it("leaves the prompt alone when the mount path is absent on disk", async () => {
    expect(await runHandler("/nonexistent/context-wiki")).toEqual({});
    expect(await runHandler(undefined)).toEqual({});
  });
});
