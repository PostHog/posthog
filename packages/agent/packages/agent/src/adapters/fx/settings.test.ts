import { describe, expect, it } from "vitest";
import { applyFxProviderSettings } from "./settings";

const provider = { baseUrl: "http://127.0.0.1:1/v1", model: "gpt-6-sol" };

describe("applyFxProviderSettings", () => {
  it.each([
    {
      name: "a global allow rule",
      existing: { permission: { bash: "allow" } },
      workspaces: undefined,
    },
    {
      name: "a workspace allow rule",
      existing: {
        workspaces: {
          "/repo": {
            permission: { bash: { "git *": "allow" } },
            additional_directories: ["/data"],
          },
        },
      },
      workspaces: { "/repo": { additional_directories: ["/data"] } },
    },
    {
      name: "global and workspace allow rules",
      existing: {
        permission: { bash: "allow" },
        workspaces: { "/repo": { permission: { edit: "allow" } } },
      },
      workspaces: { "/repo": {} },
    },
  ])(
    "drops $name so fx asks the server before every command",
    ({ existing, workspaces }) => {
      const settings = applyFxProviderSettings(existing, provider);

      expect(settings.permission).toBeUndefined();
      expect(settings.workspaces).toEqual(workspaces);
    },
  );
});
