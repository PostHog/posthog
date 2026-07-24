import { agentChatCoreModule } from "@posthog/core/agent-chat/agentChat.module";
import { autoresearchCoreModule } from "@posthog/core/autoresearch/autoresearch.module";
import { taskThreadCoreModule } from "@posthog/core/canvas/taskThread.module";
import { inboxCoreModule } from "@posthog/core/inbox/inbox.module";
import { githubConnectModule } from "@posthog/core/integrations/githubConnect.module";
import { localMcpCoreModule } from "@posthog/core/local-mcp/local-mcp.module";
import { onboardingModule } from "@posthog/core/onboarding/onboarding.module";
import { setupCoreModule } from "@posthog/core/setup/setup.module";
import { skillsCoreModule } from "@posthog/core/skills/skills.module";
import { speechCoreModule } from "@posthog/core/speech/speech.module";
import { CONTRIBUTION } from "@posthog/di/contribution";
import { agentUiModule } from "@posthog/ui/features/agent/agent.module";
import { authUiModule } from "@posthog/ui/features/auth/auth.module";
import { billingUiModule } from "@posthog/ui/features/billing/billing.module";
import { browserTabsUiModule } from "@posthog/ui/features/browser-tabs/browser-tabs.module";
import { cloneUiModule } from "@posthog/ui/features/clone/clone.module";
import { connectivityUiModule } from "@posthog/ui/features/connectivity/connectivity.module";
import { discordPresenceUiModule } from "@posthog/ui/features/discord-presence/discordPresence.module";
import { fileWatcherUiModule } from "@posthog/ui/features/file-watcher/file-watcher.module";
import { focusUiModule } from "@posthog/ui/features/focus/focus.module";
import { notificationsUiModule } from "@posthog/ui/features/notifications/notifications.module";
import { provisioningUiModule } from "@posthog/ui/features/provisioning/provisioning.module";
import { settingsUiModule } from "@posthog/ui/features/settings/settings.module";
import { setupUiModule } from "@posthog/ui/features/setup/setup.module";
import { workspaceUiModule } from "@posthog/ui/features/workspace/workspace.module";
import {
  AnalyticsBootContribution,
  InboxDemoDevContribution,
} from "@renderer/contributions/app-boot.contributions";
import { container } from "@renderer/di/container";

export function registerDesktopContributions(): void {
  for (const module of [
    agentChatCoreModule,
    agentUiModule,
    authUiModule,
    autoresearchCoreModule,
    billingUiModule,
    taskThreadCoreModule,
    browserTabsUiModule,
    cloneUiModule,
    connectivityUiModule,
    discordPresenceUiModule,
    fileWatcherUiModule,
    focusUiModule,
    githubConnectModule,
    inboxCoreModule,
    localMcpCoreModule,
    notificationsUiModule,
    onboardingModule,
    provisioningUiModule,
    settingsUiModule,
    setupCoreModule,
    setupUiModule,
    skillsCoreModule,
    speechCoreModule,
    workspaceUiModule,
  ]) {
    container.load(module);
  }

  container.bind(CONTRIBUTION).to(AnalyticsBootContribution).inSingletonScope();
  container.bind(CONTRIBUTION).to(InboxDemoDevContribution).inSingletonScope();
}
