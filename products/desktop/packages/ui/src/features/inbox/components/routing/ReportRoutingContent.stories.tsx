import type { Schemas } from "@posthog/api-client/generated";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useQueryClient } from "@tanstack/react-query";
import { InboxRoutingPreferencesContent } from "./InboxRoutingPreferencesContent";
import { ReportRoutingContent } from "./ReportRoutingContent";
import { RoutingBatchDialog } from "./RoutingBatchDialog";

const domain: Schemas.SignalProductDomain = {
  id: "11111111-1111-4111-8111-111111111111",
  name: "Checkout",
  description:
    "Purchases and confirmation. Shipment tracking belongs to Delivery.",
  owning_role_id: "22222222-2222-4222-8222-222222222222",
  owning_role_name: "Commerce",
  repository: "example/store",
  code_paths: ["src/checkout/"],
  archived: false,
  revision: 1,
  import_state: {},
};
const batch: Schemas.SignalRoutingBatch = {
  id: "44444444-4444-4444-8444-444444444444",
  domain_id: domain.id,
  status: "preview",
  total: 1,
  changed: 0,
  skipped_claims: 0,
  skipped_changes: 0,
  error: "",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};
const reportId = "33333333-3333-4333-8333-333333333333";
const state: Schemas.SignalReportRoutingState = {
  routing: {
    domain,
    owning_role_id: domain.owning_role_id ?? null,
    owning_role_name: "Commerce",
    source: "human",
    explanation: "The checkout capability needs fixing.",
    confidence: null,
    classifier_version: "",
    human_override: true,
    accepted: true,
  },
  personal: { excluded: false, has_active_claim: true },
  proposals: [],
};
const meta: Meta<typeof ReportRoutingContent> = {
  title: "Inbox/Current ownership",
  component: ReportRoutingContent,
  args: { reportId },
  parameters: {
    layout: "padded",
    testOptions: { waitForLoadersToDisappear: false },
  },
  decorators: [
    (Story, context) => {
      const cache = useQueryClient();
      cache.setQueryDefaults(["inbox-routing"], {
        staleTime: Infinity,
        refetchOnMount: false,
      });
      if (!cache.getQueryData(["inbox-routing", "catalogue"])) {
        cache.setQueryData(["inbox-routing", "catalogue"], {
          domains: [domain],
          teams: [
            { id: domain.owning_role_id, name: "Commerce", is_member: true },
          ],
          preferences: [],
          batches: [],
          suggestions: [],
        });
        cache.setQueryData(["inbox-routing", "report", reportId], state);
        cache.setQueryData(["inbox-routing", "batch", batch.id], batch);
        cache.setQueryData(["inbox-routing", "batch-reports", batch.id, 0], {
          count: 1,
          next: null,
          previous: null,
          results: [
            {
              report_id: reportId,
              title: "Purchase confirmation fails",
              status: "pending",
              has_active_claim: true,
            },
          ],
        });
      }
      return (
        <div
          style={{
            width: context.parameters.panelWidth ?? "42rem",
            maxWidth: "100%",
          }}
        >
          <Story />
        </div>
      );
    },
  ],
};
export default meta;
type Story = StoryObj<typeof ReportRoutingContent>;
export const ActiveWork: Story = {};
export const Narrow: Story = { parameters: { panelWidth: "26rem" } };
export const Preferences: Story = {
  render: () => <InboxRoutingPreferencesContent />,
};
export const Preview: Story = {
  render: () => <RoutingBatchDialog batchId={batch.id} onClose={() => {}} />,
};
