import { ApiRequestError } from "@posthog/api-client/fetcher";
import type { Schemas } from "@posthog/api-client/generated";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useLoopDraftStore } from "../loopDraftStore";
import {
  emptyLoopFormValues,
  type LoopFormValues,
  type LoopTriggerDraft,
} from "../loopFormTypes";
import { formValuesToHogFlowWrite, hogFlowToLoop } from "../loopHogFlowMapping";
import { LoopScheduleSaveError } from "../loopHogFlowWrites";
import { LoopForm } from "./LoopForm";

const mocks = vi.hoisted(() => ({
  hogFlow: undefined as unknown,
  workflowBacked: true,
  updateHogFlow: vi.fn(),
  createHogFlow: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("@posthog/ui/features/feature-flags/useLoopsHogFlowsEnabled", () => ({
  useLoopsHogFlowsEnabled: () => mocks.workflowBacked,
}));
vi.mock("@posthog/ui/features/feature-flags/useBluebirdFlag", () => ({
  useBluebirdFlag: () => false,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelsLayout", () => ({
  useChannelsLayout: () => false,
}));
vi.mock("@posthog/ui/features/sidebar/sidebarStore", () => ({
  useSidebarStore: (
    selector: (state: { channelsEnabled: boolean }) => unknown,
  ) => selector({ channelsEnabled: false }),
}));
vi.mock(
  "@posthog/ui/features/settings/sections/environments/useSandboxEnvironments",
  () => ({
    useSandboxEnvironments: () => ({ environments: [], isLoading: false }),
  }),
);
vi.mock("@posthog/ui/hooks/useSetHeaderContent", () => ({
  useSetHeaderContent: () => {},
}));
vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { error: mocks.toastError, success: vi.fn() },
}));
vi.mock("@posthog/ui/router/navigationBridge", () => ({
  navigateToLoopDetail: vi.fn(),
  navigateToLoops: vi.fn(),
}));
vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));
vi.mock("../../auth/store", () => ({
  useAuthStateValue: (
    selector: (state: { currentProjectId: string }) => unknown,
  ) => selector({ currentProjectId: "7" }),
}));
vi.mock("../hooks/useLoop", () => ({
  useLoopHogFlow: () => ({ data: mocks.hogFlow }),
}));
vi.mock("../hooks/useLoopMutations", () => {
  const idle = () => ({ mutateAsync: vi.fn(), isPending: false });
  return {
    useCreateLoop: idle,
    useUpdateLoop: idle,
    useDeleteLoop: idle,
    useCreateLoopHogFlow: () => ({
      mutateAsync: mocks.createHogFlow,
      isPending: false,
    }),
    useUpdateLoopHogFlow: () => ({
      mutateAsync: mocks.updateHogFlow,
      isPending: false,
    }),
  };
});
vi.mock("../hooks/useLoopSkillBundles", () => {
  const idle = () => ({ mutateAsync: vi.fn(), isPending: false });
  return { useBundleLocalSkill: idle, useReplaceLoopSkillBundles: idle };
});
vi.mock("@posthog/ui/features/settings/SettingsOptionSelect", () => ({
  SettingsOptionSelect: () => null,
}));
vi.mock("./LoopBehaviorFields", () => ({ LoopBehaviorFields: () => null }));
vi.mock("./LoopContextFields", () => ({ LoopContextFields: () => null }));
vi.mock("./LoopHeaderTitle", () => ({ LoopHeaderTitle: () => null }));
vi.mock("./LoopModelFields", () => ({ LoopModelFields: () => null }));
vi.mock("./LoopNotificationsFields", () => ({
  LoopNotificationsFields: () => null,
}));
vi.mock("./LoopRepositoryPicker", () => ({ LoopRepositoryPicker: () => null }));
vi.mock("./LoopSkillFields", () => ({ LoopInstructionsFields: () => null }));
vi.mock("./LoopSpaceBreadcrumb", () => ({ LoopSpaceBreadcrumb: () => null }));
vi.mock("./LoopWorkflowPromptFields", () => ({
  LoopWorkflowPromptFields: () => null,
}));
vi.mock("./LoopTriggerEditor", () => ({
  LoopTriggerEditor: ({
    triggers,
    onChange,
  }: {
    triggers: LoopTriggerDraft[];
    onChange: (triggers: LoopTriggerDraft[]) => void;
  }) => (
    <div>
      <div data-testid="triggers">
        {triggers
          .map((trigger) =>
            "cron_expression" in trigger.config
              ? trigger.config.cron_expression
              : trigger.type,
          )
          .join(",")}
      </div>
      <button type="button" onClick={() => onChange([])}>
        Remove triggers
      </button>
    </div>
  ),
}));

const PROJECT_ID = 7;

function scheduleTrigger(cron: string): LoopTriggerDraft {
  return {
    key: "t1",
    type: "schedule",
    enabled: true,
    config: { cron_expression: cron, timezone: "UTC" },
  };
}

function formValues(overrides: Partial<LoopFormValues> = {}): LoopFormValues {
  return {
    ...emptyLoopFormValues(),
    name: "Morning triage",
    instructions: "Triage the inbox.",
    triggers: [scheduleTrigger("0 9 * * *")],
    ...overrides,
  };
}

/** A workflow shaped exactly as the form writes it, with the given stamp. */
function loopShapedFlow(
  values: LoopFormValues,
  updatedAt: string,
): Schemas.HogFlow {
  const { flow, schedule } = formValuesToHogFlowWrite(values, {
    enabled: true,
  });
  return {
    id: "flow-1",
    name: flow.name,
    description: flow.description,
    status: flow.status,
    created_at: "2026-09-01T08:00:00Z",
    updated_at: updatedAt,
    actions: flow.actions,
    edges: flow.edges,
    schedules: schedule
      ? [
          {
            id: "sched-1",
            ...schedule,
            status: "active",
            next_run_at: null,
            created_at: "2026-09-01T08:00:00Z",
            updated_at: "2026-09-01T08:00:00Z",
          },
        ]
      : [],
  } as unknown as Schemas.HogFlow;
}

function renderEdit(flow: Schemas.HogFlow) {
  mocks.hogFlow = flow;
  const loop = hogFlowToLoop(flow, { projectId: PROJECT_ID });
  const view = render(<LoopForm loop={loop} variant="embedded" />);
  const rerenderWith = (nextFlow: Schemas.HogFlow) => {
    mocks.hogFlow = nextFlow;
    view.rerender(
      <LoopForm
        loop={hogFlowToLoop(nextFlow, { projectId: PROJECT_ID })}
        variant="embedded"
      />,
    );
  };
  return { ...view, rerenderWith };
}

const saveButton = () => screen.getByRole("button", { name: "Save changes" });
const nameInput = () => screen.getByPlaceholderText("Daily standup summary");

describe("LoopForm", () => {
  beforeEach(() => {
    mocks.workflowBacked = true;
    mocks.hogFlow = undefined;
    mocks.updateHogFlow.mockReset();
    mocks.createHogFlow.mockReset();
    mocks.toastError.mockReset();
    useLoopDraftStore.getState().setPrefill(null);
  });

  it("refuses to save over a workflow that no longer has the loop shape", async () => {
    const user = userEvent.setup();
    const flow = loopShapedFlow(formValues(), "2026-09-02T08:00:00Z");
    // A staged draft in the workflow editor keeps the loop readable but
    // makes the graph foreign; the form itself still looks valid.
    renderEdit({ ...flow, draft: { actions: [] } } as Schemas.HogFlow);

    await user.click(saveButton());

    expect(mocks.updateHogFlow).not.toHaveBeenCalled();
    expect(mocks.toastError).toHaveBeenCalledWith(
      "This loop was changed in the workflow editor",
      expect.anything(),
    );
  });

  it("shows the remote-change banner and blocks saving after a stale-write refusal", async () => {
    const user = userEvent.setup();
    mocks.updateHogFlow.mockRejectedValue(
      new ApiRequestError(409, "{}", { detail: "stale" }),
    );
    renderEdit(loopShapedFlow(formValues(), "2026-09-02T08:00:00Z"));

    await user.click(saveButton());

    expect(
      await screen.findByText("This loop changed elsewhere"),
    ).toBeInTheDocument();
    expect(saveButton()).toBeDisabled();
    expect(mocks.toastError).toHaveBeenCalledWith(
      "Loop changed elsewhere",
      expect.anything(),
    );
  });

  it("lets the person save again after the graph stuck but the schedule did not", async () => {
    const user = userEvent.setup();
    const values = formValues();
    const flow = loopShapedFlow(values, "2026-09-02T08:00:00Z");
    const patched = loopShapedFlow(
      { ...values, name: "Renamed" },
      "2026-09-02T09:00:00Z",
    );
    mocks.updateHogFlow.mockRejectedValueOnce(
      new LoopScheduleSaveError(new Error("rrule"), patched),
    );
    const { rerenderWith } = renderEdit(flow);

    await user.clear(nameInput());
    await user.type(nameInput(), "Renamed");
    await user.click(saveButton());
    // The mutation caches the patched graph, which arrives as a new loop.
    rerenderWith(patched);

    expect(
      screen.queryByText("This loop changed elsewhere"),
    ).not.toBeInTheDocument();
    expect(saveButton()).toBeEnabled();

    mocks.updateHogFlow.mockResolvedValueOnce(
      hogFlowToLoop(patched, { projectId: PROJECT_ID }),
    );
    await user.click(saveButton());
    expect(mocks.updateHogFlow).toHaveBeenLastCalledWith(
      expect.objectContaining({
        existing: patched,
        values: expect.objectContaining({ name: "Renamed" }),
      }),
    );
  });

  it("picks up a schedule-only change that leaves the workflow stamp alone", () => {
    const values = formValues();
    const { rerenderWith } = renderEdit(
      loopShapedFlow(values, "2026-09-02T08:00:00Z"),
    );
    expect(screen.getByTestId("triggers")).toHaveTextContent("0 9 * * *");

    rerenderWith(
      loopShapedFlow(
        { ...values, triggers: [scheduleTrigger("0 17 * * *")] },
        "2026-09-02T08:00:00Z",
      ),
    );

    expect(screen.getByTestId("triggers")).toHaveTextContent("0 17 * * *");
  });

  it("flags a schedule-only change as remote when the form has edits", async () => {
    const user = userEvent.setup();
    const values = formValues();
    const { rerenderWith } = renderEdit(
      loopShapedFlow(values, "2026-09-02T08:00:00Z"),
    );
    await user.type(nameInput(), " edited");

    rerenderWith(
      loopShapedFlow(
        { ...values, triggers: [scheduleTrigger("0 17 * * *")] },
        "2026-09-02T08:00:00Z",
      ),
    );

    expect(
      await screen.findByText("This loop changed elsewhere"),
    ).toBeInTheDocument();
    expect(saveButton()).toBeDisabled();
  });

  it("keeps a workflow loop on the trigger step until it has one trigger", async () => {
    const user = userEvent.setup();
    const flow = loopShapedFlow(formValues(), "2026-09-02T08:00:00Z");
    mocks.hogFlow = flow;
    render(<LoopForm loop={hogFlowToLoop(flow, { projectId: PROJECT_ID })} />);

    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByRole("button", { name: "Next" })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "Remove triggers" }));

    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  });

  it.each([
    {
      workflowBacked: true,
      description:
        "Pick a schedule or a GitHub event. Every loop has one trigger.",
    },
    {
      workflowBacked: false,
      description: "Add automatic triggers, or leave this manual-only.",
    },
  ])(
    "describes the When step for workflowBacked=$workflowBacked",
    ({ workflowBacked, description }) => {
      mocks.workflowBacked = workflowBacked;
      renderEdit(loopShapedFlow(formValues(), "2026-09-02T08:00:00Z"));

      expect(screen.getByText(description)).toBeInTheDocument();
    },
  );

  it("drops a space attachment from a new workflow loop and says so", async () => {
    const user = userEvent.setup();
    useLoopDraftStore.getState().setPrefill({
      ...formValues(),
      contextTarget: {
        folderId: "folder-1",
        name: "general",
        outputs: { post_to_feed: true, update_context: false, canvas_id: null },
      },
    });
    mocks.createHogFlow.mockResolvedValue(
      hogFlowToLoop(loopShapedFlow(formValues(), "2026-09-02T08:00:00Z"), {
        projectId: PROJECT_ID,
      }),
    );
    render(<LoopForm />);

    expect(
      screen.getByText("This loop won't be attached to #general"),
    ).toBeInTheDocument();

    for (let i = 0; i < 3; i += 1) {
      await user.click(screen.getByRole("button", { name: "Next" }));
    }
    await user.click(screen.getByRole("button", { name: "Create loop" }));

    await waitFor(() => expect(mocks.createHogFlow).toHaveBeenCalled());
    expect(
      mocks.createHogFlow.mock.calls[0][0].values.contextTarget,
    ).toBeNull();
  });
});
