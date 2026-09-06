import {
  ANONYMOUS_AUTH_STATE,
  useAuthStore,
} from "@posthog/ui/features/auth/store";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { scoutQueryKeys } from "../hooks/scoutQueryKeys";
import { ScoutsEmptyState } from "./ScoutsEmptyState";

const PROJECT_ID = 1;

/**
 * The empty state reads whether anything watches this project yet, so a story
 * has to answer both of those queries before it renders.
 */
function Project({
  sourcesEnabled,
  children,
}: {
  sourcesEnabled: boolean;
  children: ReactNode;
}) {
  const queryClient = useQueryClient();
  useAuthStore.setState({
    authState: {
      ...ANONYMOUS_AUTH_STATE,
      status: "authenticated",
      cloudRegion: "us",
      currentProjectId: PROJECT_ID,
    },
  });
  queryClient.setQueryData(scoutQueryKeys.configs(PROJECT_ID), []);
  queryClient.setQueryData(
    ["signals", "source-configs", PROJECT_ID],
    sourcesEnabled
      ? [{ source_product: "error_tracking", enabled: true }]
      : [{ source_product: "error_tracking", enabled: false }],
  );
  return <div className="p-6">{children}</div>;
}

const meta = {
  title: "Scouts/ScoutsEmptyState",
  component: ScoutsEmptyState,
  parameters: { layout: "fullscreen" },
  args: { onNewAgent: () => undefined },
} satisfies Meta<typeof ScoutsEmptyState>;

export default meta;

type Story = StoryObj<typeof meta>;

/** A project where nothing watches yet: sources come before agents. */
export const NothingWatching: Story = {
  decorators: [
    (Story) => (
      <Project sourcesEnabled={false}>
        <Story />
      </Project>
    ),
  ],
};

/** Sources are already on, so the only thing missing is an agent. */
export const SourcesOnNoAgents: Story = {
  decorators: [
    (Story) => (
      <Project sourcesEnabled>
        <Story />
      </Project>
    ),
  ],
};
