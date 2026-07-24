import { describe, expect, it } from "vitest";
import {
  buildRepositoryOptions,
  findRepositoryOption,
  isRepositorySelectionComplete,
  toRepositorySelection,
} from "./repositorySelection";

describe("repositorySelection", () => {
  const integrations = [
    {
      id: 7,
      kind: "github",
      display_name: "Personal GitHub",
    },
    {
      id: 11,
      kind: "github",
      config: {
        account: {
          login: "posthog",
        },
      },
    },
  ];

  it("preserves integration identity for each repository option", () => {
    const options = buildRepositoryOptions(integrations, {
      7: ["annika/mobile-app"],
      11: ["posthog/posthog", "posthog/code"],
    });

    expect(options).toEqual([
      {
        integrationId: 7,
        integrationLabel: "Personal GitHub",
        repository: "annika/mobile-app",
      },
      {
        integrationId: 11,
        integrationLabel: "posthog",
        repository: "posthog/code",
      },
      {
        integrationId: 11,
        integrationLabel: "posthog",
        repository: "posthog/posthog",
      },
    ]);
  });

  it("finds the exact repository option when multiple integrations expose the same repository", () => {
    const options = buildRepositoryOptions(integrations, {
      7: ["posthog/posthog"],
      11: ["posthog/posthog"],
    });

    const selected = findRepositoryOption(options, {
      integrationId: 11,
      repository: "posthog/posthog",
    });

    expect(selected).toEqual({
      integrationId: 11,
      integrationLabel: "posthog",
      repository: "posthog/posthog",
    });
  });

  it("converts an option into a reusable repository selection payload", () => {
    const options = buildRepositoryOptions(integrations, {
      11: ["posthog/code"],
    });

    const selection = toRepositorySelection(options[0] ?? null);

    expect(selection).toEqual({
      integrationId: 11,
      repository: "posthog/code",
    });
    expect(isRepositorySelectionComplete(selection)).toBe(true);
    expect(
      isRepositorySelectionComplete({
        integrationId: null,
        repository: "posthog/code",
      }),
    ).toBe(false);
  });
});
