import { ArtifactChip } from "@posthog/ui/primitives/ArtifactChip";
import type { Meta, StoryObj } from "@storybook/react-vite";

const meta = {
  title: "Editor/ArtifactRefChip",
  component: ArtifactChip,
} satisfies Meta<typeof ArtifactChip>;

export default meta;
type Story = StoryObj<typeof meta>;

/** How an artifact reference reads mid-sentence in an agent message. */
export const InAMessage: Story = {
  render: () => (
    <p className="max-w-lg text-[13px] leading-[1.9]">
      I've put the findings in{" "}
      <ArtifactChip
        label="report.md"
        name="report.md"
        meta="12 KB"
        onOpen={() => {}}
        onDownload={() => {}}
      />{" "}
      — open it to read the breakdown, or download it to share.
    </p>
  ),
};

export const States: Story = {
  render: () => (
    <div className="flex max-w-lg flex-col items-start gap-3 text-[13px]">
      <ArtifactChip
        label="report.md"
        name="report.md"
        meta="12 KB"
        onOpen={() => {}}
        onDownload={() => {}}
      />
      <ArtifactChip
        label="quarterly-revenue-breakdown-by-region-and-plan.csv"
        name="quarterly-revenue-breakdown-by-region-and-plan.csv"
        meta="1.4 MB"
        onOpen={() => {}}
        onDownload={() => {}}
      />
      <ArtifactChip
        label="report.md"
        name="report.md"
        meta="12 KB"
        onOpen={() => {}}
        onDownload={() => {}}
        downloading
      />
      <ArtifactChip label="report.md" name="report.md" disabled />
    </div>
  ),
};

/**
 * A long name in a narrow column, the way an activity row reads in the side
 * panel. The name truncates so the download half stays in reach.
 */
export const NarrowContainer: Story = {
  render: () => (
    <div className="flex w-56 flex-col items-start gap-3 border border-dashed p-2 text-[13px]">
      <ArtifactChip
        label="quarterly-revenue-breakdown-by-region-2026-08.csv"
        name="quarterly-revenue-breakdown-by-region-2026-08.csv"
        meta="2.4 MB"
        onOpen={() => {}}
        onDownload={() => {}}
      />
    </div>
  ),
};
