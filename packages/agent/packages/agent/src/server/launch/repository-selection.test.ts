import { describe, expect, it } from "vitest";
import { buildAppServerArgs } from "../../adapters/codex-app-server/spawn";
import { repositorySelectionCodexConfig } from "./repository-selection";

describe("repository selection", () => {
  it("disables Codex delegation and project instructions at process launch", () => {
    const args = buildAppServerArgs({
      binaryPath: "/bundle/codex",
      configOverrides: repositorySelectionCodexConfig(),
    });
    expect(args).toContain("features.multi_agent=false");
    expect(args).toContain("project_doc_max_bytes=0");
  });
});
