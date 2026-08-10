import type { Meta, StoryObj } from "@storybook/react-vite";
import { useEffect } from "react";
import { MissionControlOverlay } from "./MissionControlOverlay";
import { useMissionControlStore } from "./missionControlStore";

/**
 * The overlay is driven by a host service that only reports anything on macOS,
 * so the store is the only way to see it — here and behind the dev toolbar's
 * "Force overlay on" action alike.
 */
function ActiveOverlay() {
  useEffect(() => {
    useMissionControlStore.setState({ active: true });
    return () => useMissionControlStore.setState({ active: false });
  }, []);

  return <MissionControlOverlay />;
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
