import type {
  ExtensionAPI,
  ToolDefinition,
} from "@earendil-works/pi-coding-agent";
import { describe, expect, it } from "vitest";
import { createPiRepositoryToolsExtension } from "./repository-tools-extension";

describe("createPiRepositoryToolsExtension", () => {
  it("registers the repo-less clone and discovery tools", async () => {
    type RegisteredTool = Pick<ToolDefinition, "name" | "execute">;
    const registered: RegisteredTool[] = [];
    const extension = createPiRepositoryToolsExtension("/tmp/workspace");
    await extension.factory({
      registerTool: (tool: ToolDefinition) => {
        registered.push(tool);
      },
    } as unknown as ExtensionAPI);

    expect(registered.map((tool) => tool.name)).toEqual([
      "list_repos",
      "clone_repo",
    ]);
    const cloneTool = registered.find((tool) => tool.name === "clone_repo");
    expect(cloneTool).toBeDefined();
    await expect(
      cloneTool?.execute(
        "call-1",
        { repo: "not a repository" },
        undefined,
        undefined,
        {} as never,
      ),
    ).rejects.toThrow('clone_repo: invalid repo "not a repository"');
  });
});
