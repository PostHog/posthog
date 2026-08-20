import type { AuthState } from "@posthog/core/auth/schemas";
import { userGithubIntegrationKeys } from "@posthog/core/integrations/repositoryKeys";
import type { OnboardingStep } from "@posthog/core/onboarding/steps";
import { useHostTRPC } from "@posthog/host-router/react";
import { useAuthStore } from "@posthog/ui/features/auth/store";
import { authKeys } from "@posthog/ui/features/auth/useCurrentUser";
import { useOnboardingStore } from "@posthog/ui/features/onboarding/onboardingStore";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { useActiveRepoStore } from "@posthog/ui/shell/activeRepoStore";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { OnboardingFlow } from "./OnboardingFlow";

const INSTALLATION_ID = "51234567";
const CLOUD_REGION = "us" as const;

const REPOS = [
  "example-org/checkout-service",
  "example-org/marketing-site",
  "example-org/mobile-app",
  "acme-labs/data-pipeline",
];

const ORG_PROJECTS_MAP: AuthState["orgProjectsMap"] = {
  "org-1": {
    orgName: "Example Org",
    projects: [
      { id: 1, name: "Production" },
      { id: 2, name: "Staging" },
    ],
  },
};

const SOLO_ORG_PROJECTS_MAP: AuthState["orgProjectsMap"] = {
  "org-1": {
    orgName: "Example Org",
    projects: [{ id: 1, name: "Production" }],
  },
};

const IMPORT_SUMMARY = {
  total: 21,
  skills: { count: 9, paths: ["~/.claude/skills"] },
  plugins: { count: 3, paths: ["~/.claude/plugins"] },
  mcpServers: { count: 4, paths: ["~/.claude.json"] },
  permissions: { count: 5, paths: ["~/.claude/settings.json"] },
};

const EMPTY_IMPORT_SUMMARY = {
  total: 0,
  skills: { count: 0, paths: [] },
  plugins: { count: 0, paths: [] },
  mcpServers: { count: 0, paths: [] },
  permissions: { count: 0, paths: [] },
};

interface BranchArgs {
  step: OnboardingStep;
  githubConnected: boolean;
  hasCodeAccess: boolean;
  singleProject: boolean;
  importableConfig: boolean;
}

function authStateFor(args: BranchArgs): AuthState {
  return {
    status: "authenticated",
    bootstrapComplete: true,
    cloudRegion: CLOUD_REGION,
    orgProjectsMap: args.singleProject
      ? SOLO_ORG_PROJECTS_MAP
      : ORG_PROJECTS_MAP,
    currentOrgId: "org-1",
    currentProjectId: 1,
    hasCodeAccess: args.hasCodeAccess,
    needsScopeReauth: false,
    sessionType: "oauth",
    sessionExpiresAt: null,
    sessionEndReason: null,
  };
}

/**
 * Seeds the stores and query cache the flow reads, so each story lands on one
 * concrete branch of `computeActiveSteps` and `SelectRepoStep` without a host
 * or a network. Runs during render so the first paint is already settled.
 */
function SeededFlow(args: BranchArgs) {
  const queryClient = useQueryClient();
  const trpc = useHostTRPC();

  useState(() => {
    useAuthStore.setState({ authState: authStateFor(args) });
    useOnboardingStore.setState({
      currentStep: args.step,
      hasCompletedOnboarding: false,
      selectedProjectId: 1,
    });
    useActiveRepoStore.setState({ path: "" });
    useSettingsStore.setState({
      cachedCloudRepositoryMap: args.githubConnected
        ? Object.fromEntries(
            REPOS.map((repo) => [
              repo,
              { userIntegrationId: "1", installationId: INSTALLATION_ID },
            ]),
          )
        : {},
      lastUsedCloudRepository: null,
    });

    queryClient.setQueryData(
      userGithubIntegrationKeys.list(),
      args.githubConnected
        ? [
            {
              id: "1",
              kind: "github",
              installation_id: INSTALLATION_ID,
              account: { type: "Organization", name: "example-org" },
            },
          ]
        : [],
    );
    queryClient.setQueryData(
      userGithubIntegrationKeys.repositories(INSTALLATION_ID),
      { userIntegrationId: "1", installationId: INSTALLATION_ID, repos: REPOS },
    );
    queryClient.setQueryData(authKeys.currentUser(`${CLOUD_REGION}:1`), {
      email: "sam@example.com",
      first_name: "Sam",
      organization: { id: "org-1", name: "Example Org" },
      organizations: [{ id: "org-1", name: "Example Org", slug: "example" }],
    });
    queryClient.setQueryData(
      trpc.onboardingImport.getSummary.queryOptions().queryKey,
      args.importableConfig ? IMPORT_SUMMARY : EMPTY_IMPORT_SUMMARY,
    );
    queryClient.setQueryData(trpc.git.getGitStatus.queryOptions().queryKey, {
      installed: true,
      version: "2.43.0",
    });
    queryClient.setQueryData(trpc.git.getGhStatus.queryOptions().queryKey, {
      installed: false,
      version: null,
      authenticated: false,
      username: null,
      error: null,
    });
  });

  return <OnboardingFlow />;
}

const meta = {
  title: "Onboarding/OnboardingFlow",
  component: SeededFlow,
  parameters: {
    layout: "fullscreen",
    testOptions: { viewport: { width: 1280, height: 860 } },
  },
  args: {
    step: "welcome",
    githubConnected: true,
    hasCodeAccess: true,
    singleProject: false,
    importableConfig: true,
  },
} satisfies Meta<typeof SeededFlow>;

export default meta;

type Story = StoryObj<typeof meta>;

// The featured bento card loops a video, so no two captures match.
export const Welcome: Story = { tags: ["test-skip"] };

export const ProjectSelect: Story = { args: { step: "project-select" } };

export const InviteCode: Story = {
  args: { step: "invite-code", hasCodeAccess: false },
};

export const ConnectGithubPending: Story = {
  args: { step: "connect-github", githubConnected: false },
};

export const ConnectGithubDone: Story = { args: { step: "connect-github" } };

export const InstallCli: Story = {
  args: { step: "install-cli", githubConnected: false },
};

export const ImportConfig: Story = { args: { step: "import-config" } };

export const SelectRepoFromGithub: Story = { args: { step: "select-repo" } };

export const SelectRepoFromFolder: Story = {
  args: { step: "select-repo", githubConnected: false },
};
