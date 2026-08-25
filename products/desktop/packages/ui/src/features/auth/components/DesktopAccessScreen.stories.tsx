import type { Meta, StoryObj } from "@storybook/react-vite";
import { fn } from "storybook/test";
import { DesktopAccessScreen } from "./DesktopAccessScreen";

const meta = {
  title: "Auth/Desktop access",
  component: DesktopAccessScreen,
  parameters: { layout: "fullscreen" },
  args: {
    access: { projectId: 1, status: "blocked", reason: "startup_plan" },
    orgProjectsMap: {
      "org-1": {
        orgName: "Example organization",
        projects: [
          { id: 1, name: "Website" },
          { id: 2, name: "Mobile app" },
        ],
      },
      "org-2": {
        orgName: "Second organization",
        projects: [{ id: 3, name: "Product" }],
      },
    },
    currentOrgId: "org-1",
    currentProjectId: 1,
    isSwitching: false,
    isRetrying: false,
    isRedeemingInviteCode: false,
    isLoggingOut: false,
    switchError: null,
    redemptionError: null,
    onSelectOrganization: fn(),
    onSelectProject: fn(),
    onRedeemInviteCode: fn(),
    onRetry: fn(),
    onLogout: fn(),
    onOpenSupport: fn(),
  },
} satisfies Meta<typeof DesktopAccessScreen>;

export default meta;
type Story = StoryObj<typeof meta>;

export const StartupProgram: Story = {};

export const PrepaidCredits: Story = {
  args: {
    access: { projectId: 1, status: "blocked", reason: "prepaid_credits" },
  },
};

export const LegacyInviteCode: Story = {
  args: {
    access: { projectId: 1, status: "blocked", reason: null },
  },
};

export const TechnicalError: Story = {
  args: {
    access: { projectId: 1, status: "error", reason: null },
  },
};
