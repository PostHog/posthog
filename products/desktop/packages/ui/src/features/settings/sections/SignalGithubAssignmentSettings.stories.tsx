import {
  ANONYMOUS_AUTH_STATE,
  useAuthStore,
} from "@posthog/ui/features/auth/store";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useMemo } from "react";
import { SignalGithubAssignmentSettings } from "./SignalGithubAssignmentSettings";

const meta: Meta<typeof SignalGithubAssignmentSettings> = {
  title: "Settings/SignalGithubAssignmentSettings",
  component: SignalGithubAssignmentSettings,
  decorators: [
    (Story, context) => {
      const queryClient = useMemo(() => {
        // The autonomy hooks build a PostHog client from the auth store, and the
        // mutations hook throws when there is none.
        useAuthStore.setState({
          authState: {
            ...ANONYMOUS_AUTH_STATE,
            status: "authenticated",
            cloudRegion: "us",
            currentProjectId: 1,
          },
        });
        const client = new QueryClient();
        client.setQueryData(["signals", "user-autonomy-config"], {
          autostart_priority: "P2",
          github_assign_on_pull_request: context.parameters.assignOn === true,
        });
        return client;
      }, [context.parameters.assignOn]);
      return (
        <QueryClientProvider client={queryClient}>
          <div className="mx-auto my-8 max-w-2xl px-4">
            <Story />
          </div>
        </QueryClientProvider>
      );
    },
  ],
};

export default meta;
type Story = StoryObj<typeof SignalGithubAssignmentSettings>;

export const OptedOut: Story = {};
export const OptedIn: Story = { parameters: { assignOn: true } };
