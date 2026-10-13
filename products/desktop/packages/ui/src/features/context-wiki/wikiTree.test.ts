import { describe, expect, it } from "vitest";
import { buildWikiTree } from "./wikiTree";

describe("buildWikiTree", () => {
  it("nests flat paths into folders, creating missing intermediates", () => {
    const root = buildWikiTree([
      "AGENTS.md",
      "guides/deep/nested.md",
      "channels/growth.md",
    ]);

    expect(root.children).toEqual([
      { type: "file", name: "AGENTS", path: "AGENTS.md" },
      {
        type: "folder",
        name: "channels",
        children: [
          { type: "file", name: "growth", path: "channels/growth.md" },
        ],
      },
      {
        type: "folder",
        name: "guides",
        children: [
          {
            type: "folder",
            name: "deep",
            children: [
              { type: "file", name: "nested", path: "guides/deep/nested.md" },
            ],
          },
        ],
      },
    ]);
  });

  it("sorts AGENTS.md first within its folder, other pages alphabetically", () => {
    const root = buildWikiTree([
      "channels/zeta.md",
      "channels/AGENTS.md",
      "channels/alpha.md",
    ]);
    expect(root.children?.[0].children?.map((node) => node.name)).toEqual([
      "AGENTS",
      "alpha",
      "zeta",
    ]);
  });
});
