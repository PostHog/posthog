import type { Meta, StoryObj } from "@storybook/react-vite";
import { useEffect } from "react";
import { MissionControlOverlay } from "./MissionControlOverlay";
import { useMissionControlStore } from "./missionControlStore";

/**
 * The overlay is driven by a host service that only reports anything on macOS,
 * so the store is the only way to see it — here and behind the dev toolbar's
 * "Force overlay on" action alike.
 */
/** Ragged line lengths, so the blurred backdrop looks like real content. */
const LINE_WIDTHS = [72, 45, 88, 61, 39, 94, 55, 80, 48, 67, 91, 42, 76, 58];

/**
 * Stand-in for the app underneath. The overlay is translucent and blurred, so
 * there has to be something behind it to judge it against.
 */
function FakeAppBehind() {
  return (
    <div className="fixed inset-0 flex bg-(--gray-2)">
      <div className="w-64 shrink-0 border-(--gray-6) border-r bg-(--gray-1) p-3">
        {["Inbox", "Tasks", "Channels", "Loops", "Settings"].map((item) => (
          <div
            key={item}
            className="mb-1 rounded-(--radius-2) px-2 py-1.5 text-(--gray-11) text-sm"
          >
            {item}
          </div>
        ))}
      </div>
      <div className="flex-1 space-y-3 p-6">
        {LINE_WIDTHS.map((width) => (
          <div
            key={width}
            className="h-4 rounded-(--radius-1) bg-(--gray-4)"
            style={{ width: `${width}%` }}
          />
        ))}
      </div>
    </div>
  );
}

function ActiveOverlay() {
  useEffect(() => {
    useMissionControlStore.setState({ active: true });
    return () => useMissionControlStore.setState({ active: false });
  }, []);

  return (
    <>
      <FakeAppBehind />
      <MissionControlOverlay />
    </>
  );
}

const meta: Meta<typeof ActiveOverlay> = {
  title: "Mission Control/MissionControlOverlay",
  component: ActiveOverlay,
};

export default meta;
type Story = StoryObj<typeof ActiveOverlay>;

/**
 * What Mission Control shows for this window. Judge it shrunk to roughly a sixth
 * of its size — that is the only size it is ever seen at. Dark mode is the case
 * that matters: it exists because dark windows are hard to tell apart.
 */
export const Dark: Story = { globals: { theme: "dark" } };

export const Light: Story = { globals: { theme: "light" } };
