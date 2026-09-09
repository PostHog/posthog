import type { GatewayModel } from "@posthog/shared";
import type { ModelRolloutFlags } from "@posthog/ui/features/sessions/modelOptionFilters";
import { fireEvent, render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  availableOnboardingTestModels,
  OnboardingTestToolsDialog,
} from "./OnboardingTestToolsDialog";

const mocks = vi.hoisted(() => ({
  getCloudTaskGatewayModels: vi.fn(),
  startOnboardingTestSession: vi.fn(),
}));

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useAuthenticatedClient: () => mocks,
}));

vi.mock("@posthog/ui/features/sessions/useModelRolloutFlags", () => ({
  useModelRolloutFlags: () => rolloutFlags,
}));

vi.mock("@posthog/ui/features/settings/hooks/useOpenSettings", () => ({
  leaveSettings: vi.fn(),
}));

vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { error: vi.fn() },
}));

vi.mock("@posthog/ui/router/navigationBridge", () => ({
  navigateToChannelTask: vi.fn(),
}));

const model = (id: string, owned_by: string, allowed = true): GatewayModel => ({
  id,
  owned_by,
  context_window: 200000,
  supports_streaming: true,
  supports_vision: false,
  allowed,
});

const rolloutFlags: ModelRolloutFlags = {
  deepseek: true,
  glm: true,
  glm53: true,
  glm53Flash: true,
  kimi: true,
};

describe("availableOnboardingTestModels", () => {
  beforeEach(() => {
    mocks.getCloudTaskGatewayModels.mockReset();
    mocks.startOnboardingTestSession.mockReset();
  });

  it("keeps each supported, plan-available desktop model", () => {
    const options = availableOnboardingTestModels(
      [
        model("claude-opus-4-8", "anthropic"),
        model("@cf/zai-org/glm-5.2", "cloudflare"),
        model("gpt-5.5", "openai"),
        model("claude-fable-5", "anthropic", false),
        model("titan-express", "bedrock"),
      ],
      rolloutFlags,
    );

    expect(options.map((option) => option.value)).toEqual([
      "claude-opus-4-8",
      "@cf/zai-org/glm-5.2",
      "gpt-5.5",
    ]);
  });

  it.each([
    ["deepseek", "deepseek-ai/deepseek-v4-flash-0731", "openai"],
    ["glm", "zai-org/glm-4.6", "anthropic"],
    ["glm53", "zai-org/glm-5.3", "anthropic"],
    ["glm53Flash", "zai-org/glm-5.3-flash", "anthropic"],
    ["kimi", "moonshotai/kimi-k3", "anthropic"],
  ] as const)(
    "hides %s models when their rollout is disabled",
    (flag, gatedModel, owner) => {
      const options = availableOnboardingTestModels(
        [
          model("@cf/zai-org/glm-5.2", "cloudflare"),
          model("claude-opus-4-8", "anthropic"),
          model(gatedModel, owner),
        ],
        { ...rolloutFlags, [flag]: false },
      );

      expect(options.map((option) => option.value)).toEqual(
        flag === "glm"
          ? ["claude-opus-4-8"]
          : ["claude-opus-4-8", "@cf/zai-org/glm-5.2"],
      );
    },
  );

  it("does not create fallback choices for missing adapter models", () => {
    expect(
      availableOnboardingTestModels(
        [model("claude-opus-4-8", "anthropic")],
        rolloutFlags,
      ),
    ).toEqual([expect.objectContaining({ value: "claude-opus-4-8" })]);
    expect(availableOnboardingTestModels([], rolloutFlags)).toEqual([]);
  });

  it("submits a loaded model selection", async () => {
    mocks.getCloudTaskGatewayModels.mockResolvedValue([
      model("claude-opus-4-8", "anthropic"),
    ]);
    mocks.startOnboardingTestSession.mockResolvedValue({
      channel_id: "channel",
      task_id: "task",
    });

    render(<OnboardingTestToolsDialog open onOpenChange={vi.fn()} />);

    await waitFor(() =>
      expect(document.querySelector("input[name='model']")).toHaveValue(
        "claude-opus-4-8",
      ),
    );
    const form = document.querySelector<HTMLFormElement>(
      "form[data-slot='questionnaire']",
    );
    if (form === null) throw new Error("Questionnaire form is missing");
    fireEvent.submit(form);

    await waitFor(() =>
      expect(mocks.startOnboardingTestSession).toHaveBeenCalledWith(
        expect.objectContaining({ model: "claude-opus-4-8" }),
      ),
    );
  });
});
