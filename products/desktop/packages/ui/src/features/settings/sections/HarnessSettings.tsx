import { ShieldCheck, ShieldWarning, Warning } from "@phosphor-icons/react";
import {
  AlertDialog,
  AlertDialogClose,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
  Switch,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@posthog/quill";
import { type Adapter, ANALYTICS_EVENTS } from "@posthog/shared";
import {
  type AdapterSubscription,
  useAdapterSubscription,
} from "@posthog/ui/features/settings/adapterSubscription";
import { CopyableCommand } from "@posthog/ui/features/settings/components/CopyableCommand";
import { HarnessLogo } from "@posthog/ui/features/settings/components/HarnessLogo";
import {
  SettingsCard,
  SettingsCardRow,
} from "@posthog/ui/features/settings/components/SettingsCard";
import { ClaudeSubscriptionSettings } from "@posthog/ui/features/settings/sections/ClaudeSubscriptionSettings";
import { CodexSubscriptionSettings } from "@posthog/ui/features/settings/sections/CodexSubscriptionSettings";
import { PermissionsSettings } from "@posthog/ui/features/settings/sections/PermissionsSettings";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { useSettingsPageStore } from "@posthog/ui/features/settings/stores/settingsPageStore";
import { SUBSCRIPTION_LOGIN_ACTION } from "@posthog/ui/features/settings/subscriptionActions";
import { track } from "@posthog/ui/shell/analytics";
import { useHostCapabilities } from "@posthog/ui/shell/useHostCapabilities";
import {
  type ReactElement,
  type ReactNode,
  useCallback,
  useState,
} from "react";

type HarnessTab = Adapter | "permissions";

const HARNESS_NAMES: Record<Adapter, string> = {
  claude: "Claude Code",
  codex: "Codex",
};

const HARNESS_COMMANDS: Record<
  Adapter,
  { description: string; commands: string[] }
> = {
  claude: {
    description: "Change MCP servers, memory and hooks in a terminal",
    commands: ["claude mcp", "claude /memory", "claude /hooks"],
  },
  codex: {
    description:
      "Change MCP servers in a terminal. Review hooks with /hooks in a session",
    commands: ["codex mcp"],
  },
};

interface TabStatus {
  label: string;
  dotClass: string;
}

function harnessStatus(
  adapter: Adapter,
  subscription: AdapterSubscription,
): TabStatus | null {
  if (!subscription.flagEnabled) return null;
  if (!subscription.status) {
    return { label: "Checking", dotClass: "bg-(--gray-9)" };
  }
  if (subscription.loginState === "logged-in") {
    return {
      label: adapter === "claude" ? "Logged in" : "Connected",
      dotClass: "bg-(--green-9)",
    };
  }
  if (subscription.loginState === "logged-out") {
    return {
      label: adapter === "claude" ? "Not logged in" : "Not connected",
      dotClass: "bg-(--red-9)",
    };
  }
  return { label: "Status unknown", dotClass: "bg-(--amber-9)" };
}

function TabLabel({
  icon,
  title,
  status,
}: {
  icon: ReactNode;
  title: string;
  status: TabStatus | null;
}): ReactElement {
  return (
    <span className="flex w-full min-w-0 items-center gap-2">
      <span className="flex size-5 shrink-0 items-center justify-center">
        {icon}
      </span>
      <span className="flex min-w-0 flex-1 flex-col items-start">
        <span className="truncate">{title}</span>
        {status ? (
          <span className="@max-[600px]:hidden truncate font-normal text-[11px] text-muted-foreground">
            {status.label}
          </span>
        ) : null}
      </span>
      {status ? (
        <span
          className={`inline-block size-1.5 shrink-0 rounded-full ${status.dotClass}`}
          aria-hidden
        />
      ) : null}
    </span>
  );
}

function HarnessTabLabel({ adapter }: { adapter: Adapter }): ReactElement {
  const subscription = useAdapterSubscription(adapter);
  const { localWorkspaces } = useHostCapabilities();
  return (
    <TabLabel
      icon={<HarnessLogo adapter={adapter} />}
      title={HARNESS_NAMES[adapter]}
      status={localWorkspaces ? harnessStatus(adapter, subscription) : null}
    />
  );
}

function HarnessCommands({ adapter }: { adapter: Adapter }): ReactElement {
  const { description, commands } = HARNESS_COMMANDS[adapter];
  return (
    <SettingsCard>
      <SettingsCardRow
        stacked
        label="Terminal commands"
        description={description}
      >
        <div className="flex flex-wrap gap-1.5 pb-1">
          {commands.map((command) => (
            <CopyableCommand key={command} command={command} />
          ))}
        </div>
      </SettingsCardRow>
    </SettingsCard>
  );
}

function initialTab(): HarnessTab {
  return useSettingsPageStore.getState().initialAction ===
    SUBSCRIPTION_LOGIN_ACTION.codex
    ? "codex"
    : "claude";
}

const TRIGGER_CLASS =
  "h-auto flex-none justify-start whitespace-normal px-2 py-1.5 text-left @max-[600px]:flex-1";

export function HarnessSettings(): ReactElement {
  const { allowBypassPermissions, setAllowBypassPermissions } =
    useSettingsStore();

  const [tab, setTab] = useState<HarnessTab>(initialTab);
  const [showBypassWarning, setShowBypassWarning] = useState(false);

  const handleBypassPermissionsChange = useCallback(
    (checked: boolean) => {
      if (checked) {
        setShowBypassWarning(true);
        return;
      }

      track(ANALYTICS_EVENTS.SETTING_CHANGED, {
        setting_name: "allow_bypass_permissions",
        new_value: false,
        old_value: true,
      });
      setAllowBypassPermissions(false);
    },
    [setAllowBypassPermissions],
  );

  const handleConfirmBypassPermissions = useCallback(() => {
    track(ANALYTICS_EVENTS.SETTING_CHANGED, {
      setting_name: "allow_bypass_permissions",
      new_value: true,
      old_value: false,
    });
    setAllowBypassPermissions(true);
    setShowBypassWarning(false);
  }, [setAllowBypassPermissions]);

  return (
    <div className="@container">
      <Tabs
        orientation="vertical"
        value={tab}
        onValueChange={(value) => setTab(value as HarnessTab)}
        className="@max-[600px]:flex-col items-start @max-[600px]:items-stretch @max-[600px]:gap-4 gap-6"
      >
        <TabsList className="@max-[600px]:w-full w-48 shrink-0 @max-[600px]:flex-row gap-0.5 @max-[600px]:[&>span:last-child]:hidden">
          <TabsTrigger value="claude" className={TRIGGER_CLASS}>
            <HarnessTabLabel adapter="claude" />
          </TabsTrigger>
          <TabsTrigger value="codex" className={TRIGGER_CLASS}>
            <HarnessTabLabel adapter="codex" />
          </TabsTrigger>
          <div
            aria-hidden
            className="mx-1.5 my-1 @max-[600px]:hidden h-px bg-border"
          />
          <TabsTrigger value="permissions" className={TRIGGER_CLASS}>
            <TabLabel
              icon={
                allowBypassPermissions ? (
                  <ShieldWarning size={16} className="text-(--red-11)" />
                ) : (
                  <ShieldCheck size={16} className="text-muted-foreground" />
                )
              }
              title="Permissions"
              status={
                allowBypassPermissions
                  ? { label: "Bypass allowed", dotClass: "bg-(--red-9)" }
                  : null
              }
            />
          </TabsTrigger>
        </TabsList>

        <TabsContent
          value="claude"
          className="flex min-w-0 flex-1 flex-col gap-4"
        >
          <ClaudeSubscriptionSettings />
          <HarnessCommands adapter="claude" />
        </TabsContent>

        <TabsContent
          value="codex"
          className="flex min-w-0 flex-1 flex-col gap-4"
        >
          <CodexSubscriptionSettings />
          <HarnessCommands adapter="codex" />
        </TabsContent>

        <TabsContent
          value="permissions"
          className="flex min-w-0 flex-1 flex-col gap-2"
        >
          <p className="m-0 px-0.5 text-muted-foreground text-xs">
            What agents can do without asking you first
          </p>
          <SettingsCard>
            <PermissionsSettings />
            <SettingsCardRow
              label="Allow bypass permissions mode"
              description="Adds bypass permissions to the mode menu so you can pick it per session. Sessions keep asking for approval until you pick it. This also unlocks Full access in Codex"
            >
              <Switch
                size="sm"
                aria-label="Allow bypass permissions mode"
                checked={allowBypassPermissions}
                onCheckedChange={(checked) =>
                  handleBypassPermissionsChange(checked === true)
                }
              />
            </SettingsCardRow>
          </SettingsCard>
          {allowBypassPermissions && (
            <output className="flex gap-2 rounded-(--radius-3) border border-(--red-6) bg-(--red-2) p-3 text-(--red-11) text-xs">
              <Warning size={14} weight="fill" className="mt-0.5 shrink-0" />
              <span>
                Bypass permissions, and Full access in Codex, are now available
                in the mode menu in the prompt input. Pick one per session when
                you want that session to run shell commands, file edits and web
                requests without approval. Other sessions are unaffected.
              </span>
            </output>
          )}
        </TabsContent>
      </Tabs>

      <AlertDialog open={showBypassWarning} onOpenChange={setShowBypassWarning}>
        <AlertDialogContent className="max-w-[500px]">
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2 text-(--red-11)">
              <Warning size={20} weight="fill" />
              Allow bypass permissions mode
            </AlertDialogTitle>
            <AlertDialogDescription
              render={<div className="flex flex-col gap-3 text-sm" />}
            >
              <p className="m-0">
                This makes bypass permissions selectable in the mode menu. It
                does not turn it on for your tasks. Each session keeps its
                current mode until you pick bypass for it.
              </p>
              <p className="m-0 font-medium text-(--red-11)">
                A session running in bypass mode executes every action without
                asking, including shell commands, file edits, web requests and
                any installed MCP tools.
              </p>
              <p className="m-0">
                Pick it for sandboxed environments (containers or VMs) with
                restricted network access that can be easily restored.
              </p>
              <p className="m-0 font-medium">
                By proceeding, you accept all responsibility for actions taken
                in sessions you run with bypass.
              </p>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogClose render={<Button variant="outline" />}>
              Cancel
            </AlertDialogClose>
            <Button
              variant="destructive"
              onClick={handleConfirmBypassPermissions}
            >
              Allow bypass mode
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
