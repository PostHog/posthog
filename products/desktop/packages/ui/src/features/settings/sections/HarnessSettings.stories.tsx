import type { UserCodexIntegration } from "@posthog/api-client/posthog-client";
import { CODEX_CLOUD_ACCOUNT_SERVICE } from "@posthog/core/integrations/codexCloudAccountService";
import type { ServiceContainer } from "@posthog/di/container";
import { ServiceProvider } from "@posthog/di/react";
import {
  HostTRPCProvider,
  useHostTRPC,
  useHostTRPCClient,
} from "@posthog/host-router/react";
import {
  CLAUDE_OWN_SUBSCRIPTION_CLOUD_FLAG,
  CODEX_OWN_SUBSCRIPTION_CLOUD_FLAG,
} from "@posthog/shared";
import {
  FEATURE_FLAGS,
  type FeatureFlags,
} from "@posthog/ui/features/feature-flags/identifiers";
import {
  CLAUDE_SUBSCRIPTION_TOKEN_SETTINGS,
  type ClaudeSubscriptionTokenSettings,
} from "@posthog/ui/features/settings/claudeSubscriptionTokenSettings";
import { codexCloudAccountQueryKey } from "@posthog/ui/features/settings/codexCloudAccount";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { type ReactNode, useMemo, useState } from "react";
import { HarnessSettings } from "./HarnessSettings";

type LoginState = "logged-in" | "logged-out" | "unknown";

interface HarnessStoryParameters {
  claudeLogin?: LoginState;
  claudeToken?: boolean;
  codexLogin?: LoginState;
  codexCloud?: UserCodexIntegration["status"];
  cloudFlags?: boolean;
  permissions?: { allow: string[]; deny: string[] };
  bypass?: boolean;
  width?: number;
}

const DEFAULTS: Required<HarnessStoryParameters> = {
  claudeLogin: "logged-in",
  claudeToken: true,
  codexLogin: "logged-in",
  codexCloud: "connected",
  cloudFlags: true,
  permissions: { allow: [], deny: [] },
  bypass: false,
  width: 752,
};

function SeededHarness({
  params,
  children,
}: {
  params: Required<HarnessStoryParameters>;
  children: ReactNode;
}): ReactNode {
  const trpc = useHostTRPC();
  const [queryClient] = useState(() => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    });
    client.setQueryData(trpc.agent.claudeSubscriptionStatus.queryKey(), {
      loginState: params.claudeLogin,
      email: "you@example.com",
      organization: "Example Inc",
      subscriptionType: "team",
    });
    client.setQueryData(trpc.agent.codexSubscriptionStatus.queryKey(), {
      loginState: params.codexLogin,
      email: "you@example.com",
      subscriptionType: "business",
    });
    client.setQueryData(
      trpc.os.getClaudePermissions.queryKey(),
      params.permissions,
    );
    client.setQueryData<UserCodexIntegration>(codexCloudAccountQueryKey, {
      status: params.codexCloud,
      email: params.codexCloud === "connected" ? "you@example.com" : null,
      plan_type: params.codexCloud === "connected" ? "business" : null,
      connected_at: null,
    });
    return client;
  });
  const trpcClient = useHostTRPCClient();

  const container = useMemo((): ServiceContainer => {
    let tokenSaved = params.claudeToken;
    const tokenSettings: ClaudeSubscriptionTokenSettings = {
      has: async () => tokenSaved,
      save: async () => {
        tokenSaved = true;
      },
      clear: async () => {
        tokenSaved = false;
      },
    };
    const flags: FeatureFlags = {
      isEnabled: (key) =>
        params.cloudFlags ||
        (key !== CLAUDE_OWN_SUBSCRIPTION_CLOUD_FLAG &&
          key !== CODEX_OWN_SUBSCRIPTION_CLOUD_FLAG),
      getPayload: () => undefined,
      onFlagsLoaded: () => () => {},
    };
    const bindings = new Map<unknown, unknown>([
      [FEATURE_FLAGS, flags],
      [CLAUDE_SUBSCRIPTION_TOKEN_SETTINGS, tokenSettings],
      [CODEX_CLOUD_ACCOUNT_SERVICE, {}],
    ]);
    return {
      get: (id) => {
        if (!bindings.has(id)) throw new Error(`Unbound: ${String(id)}`);
        return bindings.get(id);
      },
      getAll: () => [],
      isBound: (id) => bindings.has(id),
      bind: () => {
        throw new Error("Story services are fixed");
      },
    } as ServiceContainer;
  }, [params.claudeToken, params.cloudFlags]);

  return (
    <QueryClientProvider client={queryClient}>
      <HostTRPCProvider trpcClient={trpcClient} queryClient={queryClient}>
        <ServiceProvider container={container}>{children}</ServiceProvider>
      </HostTRPCProvider>
    </QueryClientProvider>
  );
}

const meta: Meta<typeof HarnessSettings> = {
  title: "Settings/HarnessSettings",
  component: HarnessSettings,
  decorators: [
    (Story, context) => {
      const params = { ...DEFAULTS, ...context.parameters.harness };
      useState(() => {
        useSettingsStore.setState({
          claudeModelAccess: "own-subscription",
          codexModelAccess: "own-subscription",
          claudeCloudSubscriptionOn: params.cloudFlags,
          codexCloudSubscriptionOn: params.cloudFlags,
          allowBypassPermissions: params.bypass,
        });
      });
      return (
        <SeededHarness params={params}>
          <div className="px-6 py-6" style={{ maxWidth: params.width }}>
            <Story />
          </div>
        </SeededHarness>
      );
    },
  ],
};

export default meta;
type Story = StoryObj<typeof HarnessSettings>;

const openTab =
  (name: RegExp): Story["play"] =>
  async ({ canvas, userEvent }) => {
    await userEvent.click(await canvas.findByRole("tab", { name }));
  };

export const ClaudeConnected: Story = {};

export const ClaudeSignedOut: Story = {
  parameters: { harness: { claudeLogin: "logged-out", claudeToken: false } },
};

export const ClaudeStatusUnknown: Story = {
  parameters: { harness: { claudeLogin: "unknown" } },
};

export const CodexConnected: Story = {
  play: openTab(/Codex/),
};

export const CodexSignedOut: Story = {
  parameters: {
    harness: { codexLogin: "logged-out", codexCloud: "not_connected" },
  },
  play: openTab(/Codex/),
};

export const CodexCloudLoginExpired: Story = {
  parameters: { harness: { codexCloud: "reauth_required" } },
  play: openTab(/Codex/),
};

export const CodexLocalOnly: Story = {
  parameters: { harness: { cloudFlags: false } },
  play: openTab(/Codex/),
};

export const PermissionsEmpty: Story = {
  play: openTab(/Permissions/),
};

export const PermissionsWithRulesAndBypass: Story = {
  parameters: {
    harness: {
      bypass: true,
      permissions: {
        allow: ["Bash(git status)", "Bash(pnpm test:*)", "Read"],
        deny: ["Bash(rm -rf:*)", "WebFetch"],
      },
    },
  },
  play: openTab(/Permissions/),
};

export const BypassWarningDialog: Story = {
  play: async (context) => {
    await openTab(/Permissions/)?.(context);
    await context.userEvent.click(
      await context.canvas.findByRole("switch", {
        name: "Allow bypass permissions mode",
      }),
    );
  },
};

export const Narrow: Story = {
  parameters: {
    harness: { width: 560, codexLogin: "logged-out", bypass: true },
  },
};
