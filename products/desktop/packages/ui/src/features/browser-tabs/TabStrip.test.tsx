import { DragDropProvider } from "@dnd-kit/react";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { TabStrip, type TabView } from "./TabStrip";

const tabs: TabView[] = [
  { id: "t1", label: "Overview", channelName: "growth" },
  { id: "t2", label: "Funnels", channelName: null },
];

function setup(overrides?: Partial<Parameters<typeof TabStrip>[0]>) {
  const props = {
    tabs,
    activeTabId: "t1",
    onSelect: vi.fn(),
    onClose: vi.fn(),
    onNewTab: vi.fn(),
    onTogglePin: vi.fn(),
    onCloseOthers: vi.fn(),
    onCloseToRight: vi.fn(),
    onCloseToLeft: vi.fn(),
    ...overrides,
  };
  // Pills call useSortable, which needs an ancestor DnD provider (the app
  // mounts one in the root layout).
  render(
    <DragDropProvider>
      <TabStrip {...props} />
    </DragDropProvider>,
  );
  return props;
}

/** Open a pill's context menu (Base UI opens on the contextmenu event). */
function openMenuOn(label: string) {
  fireEvent.contextMenu(screen.getByText(label));
}

describe("TabStrip", () => {
  it("renders a pill per tab with its label", () => {
    setup();
    expect(screen.getByText("Overview")).toBeTruthy();
    expect(screen.getByText("Funnels")).toBeTruthy();
  });

  it("marks the active tab as selected", () => {
    setup({ activeTabId: "t2" });
    const selected = screen
      .getAllByRole("tab")
      .filter((el) => el.getAttribute("aria-selected") === "true");
    expect(selected).toHaveLength(1);
    expect(selected[0].textContent).toContain("Funnels");
  });

  it("calls onSelect with the tab id when a pill is clicked", async () => {
    const props = setup();
    await userEvent.click(screen.getByText("Funnels"));
    expect(props.onSelect).toHaveBeenCalledWith("t2");
  });

  it("closes without selecting when the close affordance is clicked", async () => {
    const props = setup();
    await userEvent.click(screen.getByLabelText("Close Funnels"));
    expect(props.onClose).toHaveBeenCalledWith("t2");
    expect(props.onSelect).not.toHaveBeenCalled();
  });

  it("calls onNewTab when the new-tab button is clicked", async () => {
    const props = setup();
    await userEvent.click(screen.getByLabelText("New tab"));
    expect(props.onNewTab).toHaveBeenCalledTimes(1);
  });

  it("hides the new-tab button when onNewTab is omitted", () => {
    setup({ onNewTab: undefined });
    expect(screen.queryByLabelText("New tab")).toBeNull();
  });

  it("collapses a pinned tab to an icon-only pill without a close affordance", () => {
    setup({
      tabs: [{ ...tabs[0], pinned: true }, tabs[1]],
    });
    expect(screen.queryByLabelText("Close Overview")).toBeNull();
    expect(screen.queryByText("Overview")).toBeNull();
    expect(screen.getByLabelText("Overview (pinned)")).toBeTruthy();
    expect(screen.getByLabelText("Close Funnels")).toBeTruthy();
  });

  it("pins from the context menu", async () => {
    const props = setup();
    openMenuOn("Overview");
    await userEvent.click(await screen.findByText("Pin tab"));
    expect(props.onTogglePin).toHaveBeenCalledWith("t1");
  });

  it("offers Unpin for a pinned tab", async () => {
    const props = setup({ tabs: [{ ...tabs[0], pinned: true }, tabs[1]] });
    fireEvent.contextMenu(screen.getByLabelText("Overview (pinned)"));
    await userEvent.click(await screen.findByText("Unpin tab"));
    expect(props.onTogglePin).toHaveBeenCalledWith("t1");
  });

  it("closes tabs to the right from the context menu", async () => {
    const props = setup();
    openMenuOn("Overview");
    await userEvent.click(await screen.findByText("Close tabs to the right"));
    expect(props.onCloseToRight).toHaveBeenCalledWith("t1");
  });

  it("disables bulk closes with nothing to close", async () => {
    setup();
    openMenuOn("Overview");
    // First tab: nothing to its left; only unpinned t2 to the right.
    const left = await screen.findByText("Close tabs to the left");
    expect(left.closest("[role=menuitem]")?.getAttribute("aria-disabled")).toBe(
      "true",
    );
  });

  it("disables bulk closes when the other tabs are pinned", async () => {
    setup({ tabs: [tabs[0], { ...tabs[1], pinned: true }] });
    openMenuOn("Overview");
    const others = await screen.findByText("Close other tabs");
    expect(
      others.closest("[role=menuitem]")?.getAttribute("aria-disabled"),
    ).toBe("true");
  });
});
