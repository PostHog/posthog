import {
  CanvasListService,
  DEFAULT_CANVAS_LIST_SETTINGS,
} from "@posthog/core/canvas/canvasListService";
import type { DashboardRecord } from "@posthog/core/canvas/dashboardSchemas";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { type ReactElement, useMemo, useState } from "react";
import { expect, waitFor } from "storybook/test";
import { CanvasList } from "./CanvasList";

const service = new CanvasListService();
const canvases: DashboardRecord[] = Array.from({ length: 1000 }, (_, i) => ({
  id: `canvas-${i}`,
  channelId: "example-space",
  name: `Canvas ${String(i + 1).padStart(4, "0")}`,
  kind: "freeform",
  description: "",
  templateId: "freeform",
  createdBy: "Example author",
  createdAt: new Date(2026, 0, 1).getTime() - i * 1000,
  updatedAt: new Date(2026, 0, 1).getTime() - i * 1000,
}));
function Harness({ count }: { count: number }): ReactElement {
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string>();
  const [openedName, setOpenedName] = useState<string>();
  const viewModel = useMemo(
    () =>
      service.buildViewModel({
        canvases: canvases.slice(0, count),
        spaces: [],
        settings: DEFAULT_CANVAS_LIST_SETTINGS,
        query,
        lastViewedAtByCanvasId: {},
        now: new Date(2026, 0, 1, 12),
      }),
    [count, query],
  );
  return (
    <div className="flex h-[600px] w-full flex-col">
      <CanvasList
        className="min-h-0 flex-1"
        viewModel={viewModel}
        query={query}
        setQuery={setQuery}
        lastViewedAtByCanvasId={{}}
        selectedId={selectedId}
        open={(canvas) => {
          setSelectedId(canvas.id);
          setOpenedName(canvas.name);
        }}
      />
      <output className="border-t p-2 text-xs">
        {openedName ? `Opened ${openedName}` : "Nothing opened"}
      </output>
    </div>
  );
}
const meta = {
  title: "Canvases/CanvasList",
  component: Harness,
  args: { count: 1000 },
} satisfies Meta<typeof Harness>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Large: Story = {};
export const Small: Story = { args: { count: 3 } };

export const KeyboardNavigation: Story = {
  play: async ({ canvas, userEvent }): Promise<void> => {
    const input = canvas.getByRole("combobox");
    await canvas.findByRole("option", { name: /Canvas 0001/ });
    await expect(canvas.getAllByRole("option").length).toBeLessThan(40);
    await expect(
      canvas.getByRole("option", { name: /Canvas 0001/ }),
    ).toHaveAttribute("aria-setsize", "1000");
    await userEvent.click(input);
    await userEvent.keyboard("{End}");
    const last = await canvas.findByRole("option", { name: /Canvas 1000/ });
    await waitFor(() =>
      expect(input).toHaveAttribute("aria-activedescendant", last.id),
    );
    await userEvent.keyboard("{Enter}");
    await canvas.findByText("Opened Canvas 1000");
    await userEvent.click(input);
    await userEvent.keyboard("{Home}");
    const first = await canvas.findByRole("option", { name: /Canvas 0001/ });
    await waitFor(() =>
      expect(input).toHaveAttribute("aria-activedescendant", first.id),
    );
    await userEvent.keyboard("{Enter}");
    await canvas.findByText("Opened Canvas 0001");
    await userEvent.type(input, "Canvas 0500");
    await canvas.findByRole("option", { name: /Canvas 0500/ });
    await expect(canvas.getAllByRole("option")).toHaveLength(1);
    await userEvent.keyboard("{ArrowDown}{Enter}");
    await canvas.findByText("Opened Canvas 0500");
    await userEvent.click(input);
    await userEvent.keyboard("{Escape}");
    await canvas.findByRole("option", { name: /Canvas 0001/ });
    await expect(canvas.getAllByRole("option").length).toBeLessThan(40);
  },
};
