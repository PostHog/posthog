import { LockSimpleIcon } from "@phosphor-icons/react";
import {
  type CanvasListGrouping,
  type CanvasListSort,
  DEFAULT_CANVAS_LIST_GROUPING,
  DEFAULT_CANVAS_LIST_SORT,
} from "@posthog/ui/features/canvas/components/canvasList";
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
  { value: "", label: "Every space" },
  { value: "engineering", label: "engineering" },
];

const CREATOR_OPTIONS = [
  { value: "", label: "Anyone" },
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
}: {
  initialSpaceIds: string[];
  initialCreatorUuids: string[];
  initialSort: CanvasListSort;
  initialGrouping: CanvasListGrouping;
}): ReactElement {
  const [spaceIds, setSpaceIds] = useState(initialSpaceIds);
  const [creatorUuids, setCreatorUuids] = useState(initialCreatorUuids);
  const [sort, setSort] = useState(initialSort);
  const [grouping, setGrouping] = useState(initialGrouping);
  const active =
    spaceIds.length > 0 ||
    creatorUuids.length > 0 ||
    sort !== DEFAULT_CANVAS_LIST_SORT ||
    grouping !== DEFAULT_CANVAS_LIST_GROUPING;

  return (
    <div className="flex justify-end p-2">
      <CanvasFilterMenu
        spaceOptions={SPACE_OPTIONS}
        spaceIds={spaceIds}
        onSpaceChange={setSpaceIds}
        creatorOptions={CREATOR_OPTIONS}
        creatorUuids={creatorUuids}
        onCreatorChange={setCreatorUuids}
        sort={sort}
        onSortChange={setSort}
        grouping={grouping}
        onGroupingChange={setGrouping}
        onClear={() => {
          setSpaceIds([]);
          setCreatorUuids([]);
          setSort(DEFAULT_CANVAS_LIST_SORT);
          setGrouping(DEFAULT_CANVAS_LIST_GROUPING);
        }}
        active={active}
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
    initialSort: DEFAULT_CANVAS_LIST_SORT,
    initialGrouping: DEFAULT_CANVAS_LIST_GROUPING,
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
