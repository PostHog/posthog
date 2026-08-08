import { ArtifactChipShell } from "@posthog/ui/features/editor/components/ArtifactRefChip";
import type { Meta, StoryObj } from "@storybook/react-vite";

const meta = {
  title: "Editor/ArtifactRefChip",
  component: ArtifactChipShell,
} satisfies Meta<typeof ArtifactChipShell>;

export default meta;
type Story = StoryObj<typeof meta>;

/** How an artifact reference reads mid-sentence in an agent message. */
export const InAMessage: Story = {
  render: () => (
    <p className="max-w-lg text-[13px] leading-[1.9]">
      I've put the findings in{" "}
      <ArtifactChipShell
        label="report.md"
        name="report.md"
        sizeLabel="12 KB"
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
      <ArtifactChipShell
        label="report.md"
        name="report.md"
        sizeLabel="12 KB"
        onOpen={() => {}}
        onDownload={() => {}}
      />
      <ArtifactChipShell
        label="quarterly-revenue-breakdown-by-region-and-plan.csv"
        name="quarterly-revenue-breakdown-by-region-and-plan.csv"
        sizeLabel="1.4 MB"
        onOpen={() => {}}
        onDownload={() => {}}
      />
      <ArtifactChipShell
        label="report.md"
        name="report.md"
        sizeLabel="12 KB"
        onOpen={() => {}}
        onDownload={() => {}}
        downloading
      />
      <ArtifactChipShell label="report.md" name="report.md" disabled />
    </div>
  ),
};
