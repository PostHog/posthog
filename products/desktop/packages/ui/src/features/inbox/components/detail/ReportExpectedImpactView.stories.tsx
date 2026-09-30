import type { ImpactMeasurementPlanArtefact } from "@posthog/shared/types";
import type { Meta, StoryObj } from "@storybook/react";
import { ReportChartCardView } from "./ReportChartCard";
import { ReportExpectedImpactView } from "./ReportExpectedImpactSection";

const proposed: ImpactMeasurementPlanArtefact = {
  id: "plan-1",
  type: "impact_measurement_plan",
  created_at: "2026-09-01T00:00:00Z",
  content: {
    metric_id: "export_failures",
    title: "Failed exports",
    query: { kind: "InsightVizNode", source: { kind: "TrendsQuery" } },
    value_format: "count",
    unit: "failures",
    goal_value: 20,
    goal_direction: "at_most",
    goal_grain: "per_interval",
    decision_window_days: 7,
    minimum_data_points: 200,
    activated: false,
    retired: false,
  },
};

const redacted: ImpactMeasurementPlanArtefact = {
  id: "plan-2",
  type: "impact_measurement_plan",
  created_at: "2026-09-01T00:00:00Z",
  content: {
    metric_id: "retries",
    title: "Export retries",
    activated: true,
    retired: false,
  },
};

const meta: Meta<typeof ReportExpectedImpactView> = {
  title: "Inbox/ReportExpectedImpact",
  component: ReportExpectedImpactView,
  args: {
    plans: [proposed, redacted],
    pendingCount: 1,
    onSaveInWeb: () => {},
    renderChart: (artefact) => (
      <ReportChartCardView
        chartId={artefact.id}
        title={artefact.content.title}
        heightClass="h-56"
        openTarget={null}
        state={{
          kind: "data",
          data: {
            type: "series",
            render: "bar",
            labels: ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"],
            series: [{ key: "s0", label: "failures", data: [48, 36, 25, 18] }],
            isTimeSeries: true,
            interval: "day",
          },
        }}
      />
    ),
  },
  decorators: [
    (Story) => (
      <div className="max-w-[640px]">
        <Story />
      </div>
    ),
  ],
};
export default meta;

type Story = StoryObj<typeof ReportExpectedImpactView>;

export const ProposedAndRedacted: Story = {};
