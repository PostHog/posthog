import { Autocomplete, Button } from "@posthog/quill";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { SidebarSearchHeader } from "./SidebarSearchHeader";

const meta = {
  title: "Canvas/SidebarSearchHeader",
  component: SidebarSearchHeader,
  decorators: [
    (Story) => (
      <Autocomplete<string> value="" items={[]} filter={null}>
        <div className="w-72 bg-chrome">
          <Story />
        </div>
      </Autocomplete>
    ),
  ],
  args: {
    title: "Activity",
    query: "",
    placeholder: "Search activity…",
    searchLabel: "Search activity",
    onClear: () => {},
  },
} satisfies Meta<typeof SidebarSearchHeader>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const WithActions: Story = {
  args: {
    actions: <Button size="xs">Unreads</Button>,
  },
};
