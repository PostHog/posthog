import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ScoutConfigForm } from "./ScoutConfigControls";

vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: () => true,
}));

function makeConfig(overrides: Partial<ScoutConfig> = {}): ScoutConfig {
  return {
    id: "config-1",
    skill_name: "error-tracking",
    enabled: true,
    emit: true,
    run_interval_minutes: 60,
    last_run_at: null,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("ScoutConfigForm", () => {
  // `model` is optional in the contract: an absent field means the backend
  // predates it and a PATCH cannot persist, so the input must stay hidden even
  // with the flag on. An explicit null is the writable "use default" state.
  it.each([
    {
      name: "absent (backend predates the field)",
      model: undefined,
      shown: false,
    },
    { name: "explicit null (writable default)", model: null, shown: true },
    { name: "pinned model id", model: "claude-opus-4-5", shown: true },
  ])("model $name → input shown: $shown", ({ model, shown }) => {
    render(
      <Theme>
        <ScoutConfigForm config={makeConfig({ model })} onUpdate={vi.fn()} />
      </Theme>,
    );

    const input = screen.queryByLabelText("error-tracking model");
    expect(input === null).toBe(!shown);
  });
});
