import { ArrowSquareOut, Check, Copy, Warning } from "@phosphor-icons/react";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
  Switch,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import {
  SettingsCard,
  SettingsCardRow,
  SettingsSection,
} from "@posthog/ui/features/settings/components/SettingsCard";
import { CodexSubscriptionSettings } from "@posthog/ui/features/settings/sections/CodexSubscriptionSettings";
import { PermissionsSettings } from "@posthog/ui/features/settings/sections/PermissionsSettings";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import { track } from "@posthog/ui/shell/analytics";
import { useCallback, useState } from "react";

function CopyableCommand({ command }: { command: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(command);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [command]);

  return (
    <div className="flex items-center gap-2 rounded border border-gray-6 bg-gray-2 px-2 py-1">
      <span className="text-[13px] text-gray-11">{command}</span>
      <Tooltip content={copied ? "Copied!" : "Copy"}>
        <Button variant="link-muted" size="icon-xs" onClick={handleCopy}>
          {copied ? <Check size={12} /> : <Copy size={12} />}
        </Button>
      </Tooltip>
    </div>
  );
}

function SettingDescription({
  text,
  docsUrl,
}: {
  text: string;
  docsUrl: string;
}) {
  return (
    <span className="flex flex-col gap-1">
      <span>{text}</span>
      <a
        href={docsUrl}
        target="_blank"
        rel="noreferrer"
        className="flex items-center gap-1 text-(--accent-11) hover:underline"
      >
        Documentation
        <ArrowSquareOut size={10} />
      </a>
    </span>
  );
}

export function HarnessSettings() {
  const { allowBypassPermissions, setAllowBypassPermissions } =
    useSettingsStore();

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
    <div className="flex flex-col gap-7">
      <SettingsSection
        label="Claude Code"
        description="Applies to sessions that run on the Claude Code agent. It reads your own Claude configuration"
      >
        <SettingsCard>
          <SettingsCardRow
            label="MCP servers"
            description={
              <SettingDescription
                text="Extend Claude's capabilities with MCP servers"
                docsUrl="https://docs.anthropic.com/en/docs/claude-code/mcp"
              />
            }
          >
            <CopyableCommand command="claude mcp" />
          </SettingsCardRow>
          <SettingsCardRow
            label="Skills"
            description={
              <SettingDescription
                text="Create custom slash commands in ~/.claude/skills/"
                docsUrl="https://docs.anthropic.com/en/docs/claude-code/slash-commands"
              />
            }
          />
          <SettingsCardRow
            label="Memory"
            description={
              <SettingDescription
                text="Persistent context stored in CLAUDE.md files"
                docsUrl="https://docs.anthropic.com/en/docs/claude-code/memory"
              />
            }
          >
            <CopyableCommand command="claude /memory" />
          </SettingsCardRow>
          <SettingsCardRow
            label="Hooks"
            description={
              <SettingDescription
                text="Execute commands at specific points in Claude's lifecycle"
                docsUrl="https://docs.anthropic.com/en/docs/claude-code/hooks"
              />
            }
          >
            <CopyableCommand command="claude /hooks" />
          </SettingsCardRow>
        </SettingsCard>
      </SettingsSection>

      <SettingsSection
        label="Codex"
        description="Applies to sessions that run on the Codex agent. It reads your own Codex configuration"
      >
        <SettingsCard>
          <CodexSubscriptionSettings />
          <SettingsCardRow
            label="MCP servers"
            description={
              <SettingDescription
                text="Extend Codex's capabilities with MCP servers"
                docsUrl="https://learn.chatgpt.com/docs/extend/mcp"
              />
            }
          >
            <CopyableCommand command="codex mcp" />
          </SettingsCardRow>
          <SettingsCardRow
            label="Skills"
            description={
              <SettingDescription
                text="Reusable instructions in .agents/skills/, mentioned with $skill-name"
                docsUrl="https://learn.chatgpt.com/docs/build-skills"
              />
            }
          />
          <SettingsCardRow
            label="Memory"
            description={
              <SettingDescription
                text="Persistent context stored in AGENTS.md files"
                docsUrl="https://learn.chatgpt.com/docs/agent-configuration/agents-md"
              />
            }
          />
          <SettingsCardRow
            label="Hooks"
            description={
              <SettingDescription
                text="Execute commands at specific points in Codex's lifecycle, defined in .codex/hooks.json or config.toml. Review them with /hooks inside a session"
                docsUrl="https://learn.chatgpt.com/docs/hooks"
              />
            }
          />
        </SettingsCard>
      </SettingsSection>

      <SettingsSection
        label="Permissions"
        description="What sessions may do without asking you first. Applies to both agents unless noted"
      >
        <SettingsCard>
          <SettingsCardRow
            label="Claude permission rules"
            description="Tool permissions from your Claude settings. Allowed tools run without prompting. Denied tools are always blocked. Codex keeps its own rules in config.toml"
          >
            <CopyableCommand command="claude config" />
          </SettingsCardRow>
        </SettingsCard>

        <PermissionsSettings />

        <SettingsCard>
          <SettingsCardRow
            label="Allow bypass permissions mode"
            description="Adds bypass permissions to the mode menu so you can pick it per session. Sessions keep asking for approval until you pick it. This also unlocks Full access in Codex"
          >
            <Switch
              size="sm"
              checked={allowBypassPermissions}
              onCheckedChange={handleBypassPermissionsChange}
            />
          </SettingsCardRow>
        </SettingsCard>
        {allowBypassPermissions && (
          <div className="flex items-start gap-2 rounded-(--radius-3) border border-(--red-6) bg-(--red-2) p-3 text-(--red-11) text-[13px]">
            <Warning weight="fill" size={16} className="mt-0.5 shrink-0" />
            <span>
              Bypass permissions, and Full access in Codex, are now available in
              the mode menu in the prompt input. Pick one per session when you
              want that session to run shell commands, file edits and web
              requests without approval. Other sessions are unaffected.
            </span>
          </div>
        )}
      </SettingsSection>

      <AlertDialog open={showBypassWarning} onOpenChange={setShowBypassWarning}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              <span className="flex items-center gap-2 text-(--red-11)">
                <Warning size={20} weight="fill" />
                Allow bypass permissions mode
              </span>
            </AlertDialogTitle>
            <AlertDialogDescription>
              <span className="flex flex-col gap-3">
                <span>
                  This makes bypass permissions selectable in the mode menu. It
                  does not turn it on for your tasks. Each session keeps its
                  current mode until you pick bypass for it.
                </span>
                <span className="font-medium text-(--red-11)">
                  A session running in bypass mode executes every action without
                  asking, including shell commands, file edits, web requests and
                  any installed MCP tools.
                </span>
                <span>
                  Pick it for sandboxed environments (containers or VMs) with
                  restricted network access that can be easily restored.
                </span>
                <span className="font-medium">
                  By proceeding, you accept all responsibility for actions taken
                  in sessions you run with bypass.
                </span>
              </span>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowBypassWarning(false)}
            >
              Cancel
            </Button>
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
