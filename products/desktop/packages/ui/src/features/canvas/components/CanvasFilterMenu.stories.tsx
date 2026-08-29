import { LockSimpleIcon } from "@phosphor-icons/react";
import type {
  CanvasListGrouping,
  CanvasListSettings,
  CanvasListSort,
} from "@posthog/core/canvas/canvasListService";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { type ReactElement, useState } from "react";
import { within } from "storybook/test";
import { CanvasFilterMenu } from "./CanvasFilterMenu";

const SPACE_OPTIONS = [
  {
    value: "personal",
    label: "personal",
    icon: <LockSimpleIcon size={16} />,
  },
  { value: null, label: "Every space" },
  { value: "engineering", label: "engineering" },
];

const CREATOR_OPTIONS = [
  { value: null, label: "Anyone" },
  { value: "me", label: "Me" },
  { value: "ada", label: "Ada Lovelace" },
  { value: "grace", label: "Grace Hopper" },
  { value: "alan", label: "Alan Turing" },
  { value: "barbara", label: "Barbara Liskov" },
  { value: "donald", label: "Donald Knuth" },
  { value: "evelyn", label: "Evelyn Boyd Granville" },
  { value: "frances", label: "Frances Allen" },
  { value: "john", label: "John McCarthy" },
  { value: "katherine", label: "Katherine Johnson" },
  { value: "margaret", label: "Margaret Hamilton" },
  { value: "mary", label: "Mary Jackson" },
  { value: "radia", label: "Radia Perlman" },
  { value: "sophie", label: "Sophie Wilson" },
  { value: "tim", label: "Tim Berners-Lee" },
  { value: "yukihiro", label: "Yukihiro Matsumoto" },
];

function Harness({
  initialSpaceIds,
  initialCreatorUuids,
  initialSort,
  initialGrouping,
  createdByDisabled,
}: {
  initialSpaceIds: string[];
  initialCreatorUuids: string[];
  initialSort: CanvasListSort;
  initialGrouping: CanvasListGrouping;
  createdByDisabled: boolean;
}): ReactElement {
  const [settings, setSettings] = useState<CanvasListSettings>({
    spaceIds: initialSpaceIds,
    creatorUuids: initialCreatorUuids,
    sort: initialSort,
    grouping: initialGrouping,
  });

  return (
    <div className="flex justify-end p-2">
      <CanvasFilterMenu
        spaceOptions={SPACE_OPTIONS}
        creatorOptions={CREATOR_OPTIONS}
        createdByDisabled={createdByDisabled}
        settings={settings}
        onChange={setSettings}
      />
    </div>
  );
}

const meta: Meta<typeof Harness> = {
  title: "Canvases/CanvasFilterMenu",
  component: Harness,
  args: {
    initialSpaceIds: [],
    initialCreatorUuids: [],
    initialSort: "recently_viewed",
    initialGrouping: "date",
    createdByDisabled: false,
  },
  decorators: [
    (Story): ReactElement => (
      <div className="w-64 border border-border">
        <Story />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof Harness>;

export const Default: Story = {};

export const MenuOpen: Story = {
  play: async ({ canvas, userEvent }): Promise<void> => {
    await userEvent.click(canvas.getByLabelText("Filter canvases"));
  },
};

export const CreatedByOpen: Story = {
  args: {
    initialCreatorUuids: ["me", "ada", "grace"],
  },
  play: async ({ canvas, canvasElement, userEvent }): Promise<void> => {
    const body = within(canvasElement.ownerDocument.body);
    await userEvent.click(canvas.getByLabelText("Filter canvases"));
    await userEvent.hover(await body.findByText("Created by"));
    await body.findByLabelText("Search users…");
  },
};

export const FilteredAndGrouped: Story = {
  args: {
    initialSpaceIds: ["personal", "engineering"],
    initialCreatorUuids: ["me", "ada", "grace"],
    initialSort: "created_by",
    initialGrouping: "space",
  },
};

export const PersonalSpace: Story = {
  args: {
    initialSpaceIds: ["personal"],
    initialCreatorUuids: ["me"],
    createdByDisabled: true,
  },
  play: async ({ canvas, userEvent }): Promise<void> => {
    await userEvent.click(canvas.getByLabelText("Filter canvases"));
  },
};
