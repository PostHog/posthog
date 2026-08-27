import type { AgentFlowDefinition } from "@posthog/shared";
import { AGENT_FLOW_EFFORT_LABELS, AGENT_FLOW_ROLE_META } from "./roleMeta";

export function FlowSummary({ flow }: { flow: AgentFlowDefinition }) {
  return (
    <div
      className="rounded-lg p-2"
      style={{
        backgroundImage: "radial-gradient(var(--gray-a4) 1px, transparent 1px)",
        backgroundSize: "16px 16px",
      }}
    >
      {flow.steps.map((step, stepIndex) => {
        const meta = AGENT_FLOW_ROLE_META[step.role];
        const RoleIcon = meta.icon;
        return (
          <div key={step.id} className="flex flex-col">
            <div className="overflow-hidden rounded-lg border border-gray-6 bg-gray-1 shadow-xs">
              <div className="flex items-center gap-1.5 border-gray-4 border-b bg-gray-2 px-2 py-1">
                <span
                  className={`flex size-5 shrink-0 items-center justify-center rounded ${meta.chipClass}`}
                >
                  <RoleIcon size={12} weight="bold" />
                </span>
                <span className="min-w-0 flex-1 truncate font-semibold text-[13px] text-gray-12">
                  {step.name}
                </span>
                <span className="shrink-0 text-[11px] text-gray-9 tabular-nums">
                  {stepIndex + 1}/{flow.steps.length}
                </span>
              </div>
              <div className="flex flex-col gap-1 px-2 py-1.5">
                <p className="text-[12px] text-gray-10">
                  {step.model.name} · {AGENT_FLOW_EFFORT_LABELS[step.effort]}
                </p>
                {step.instructions ? (
                  <p className="text-[12px] text-gray-11">
                    {step.instructions}
                  </p>
                ) : null}
              </div>
            </div>

            {stepIndex < flow.steps.length - 1 ? (
              <div className="flex flex-col items-center gap-1 py-1">
                <div className="h-2.5 w-px bg-gray-7" />
                {step.approvalAfter ? (
                  <span className="rounded-full border border-blue-6 bg-blue-2 px-2 py-0.5 text-[11px] text-blue-11">
                    Waits for your approval
                  </span>
                ) : null}
                <div className="h-2.5 w-px bg-gray-7" />
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
