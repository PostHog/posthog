import { ArrowSquareOut, Check, Copy, Warning } from "@phosphor-icons/react";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { SettingRow } from "@posthog/ui/features/settings/SettingRow";
import { PermissionsSettings } from "@posthog/ui/features/settings/sections/PermissionsSettings";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import { track } from "@posthog/ui/shell/analytics";
import {
  AlertDialog,
  Button,
  Callout,
  Flex,
  IconButton,
  Link,
  Switch,
  Text,
} from "@radix-ui/themes";
import { useCallback, useState } from "react";

function CopyableCommand({ command }: { command: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(command);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [command]);

  return (
    <Flex
      align="center"
      gap="2"
      className="rounded border border-gray-6 bg-gray-2 px-2 py-1"
    >
      <Text className="text-[13px] text-gray-11">{command}</Text>
      <Tooltip content={copied ? "Copied!" : "Copy"}>
        <IconButton
          variant="ghost"
          size="1"
          color={copied ? "green" : "gray"}
          onClick={handleCopy}
        >
          {copied ? <Check size={12} /> : <Copy size={12} />}
        </IconButton>
      </Tooltip>
    </Flex>
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
    <Flex direction="column" gap="1">
      <Text color="gray" className="text-[13px]">
        {text}
      </Text>
      <Link href={docsUrl} target="_blank" className="text-[13px]">
        <Flex align="center" gap="1">
          Documentation
          <ArrowSquareOut size={10} />
        </Flex>
      </Link>
    </Flex>
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
    <Flex direction="column">
      {/* Claude Code */}
      <Text className="mt-1 mb-2 font-medium text-sm">Claude Code</Text>

      <SettingRow
        label="MCP servers"
        description={
          <SettingDescription
            text="Extend Claude's capabilities with MCP servers"
            docsUrl="https://docs.anthropic.com/en/docs/claude-code/mcp"
          />
        }
      >
        <CopyableCommand command="claude mcp" />
      </SettingRow>

      <SettingRow
        label="Skills"
        description={
          <SettingDescription
            text="Create custom slash commands in ~/.claude/skills/"
            docsUrl="https://docs.anthropic.com/en/docs/claude-code/slash-commands"
          />
        }
      >
        <span />
      </SettingRow>

      <SettingRow
        label="Memory"
        description={
          <SettingDescription
            text="Persistent context stored in CLAUDE.md files"
            docsUrl="https://docs.anthropic.com/en/docs/claude-code/memory"
          />
        }
      >
        <CopyableCommand command="claude /memory" />
      </SettingRow>

      <SettingRow
        label="Hooks"
        description={
          <SettingDescription
            text="Execute commands at specific points in Claude's lifecycle"
            docsUrl="https://docs.anthropic.com/en/docs/claude-code/hooks"
          />
        }
        noBorder
      >
        <CopyableCommand command="claude /hooks" />
      </SettingRow>

      {/* Codex */}
      <Text className="mb-2 block border-gray-6 border-t pt-4 font-medium text-sm">
        Codex
      </Text>

      <SettingRow
        label="MCP servers"
        description={
          <SettingDescription
            text="Extend Codex's capabilities with MCP servers"
            docsUrl="https://learn.chatgpt.com/docs/extend/mcp"
          />
        }
      >
        <CopyableCommand command="codex mcp" />
      </SettingRow>

      <SettingRow
        label="Skills"
        description={
          <SettingDescription
            text="Reusable instructions in .agents/skills/, mentioned with $skill-name"
            docsUrl="https://learn.chatgpt.com/docs/build-skills"
          />
        }
      >
        <span />
      </SettingRow>

      <SettingRow
        label="Memory"
        description={
          <SettingDescription
            text="Persistent context stored in AGENTS.md files"
            docsUrl="https://learn.chatgpt.com/docs/agent-configuration/agents-md"
          />
        }
      >
        <span />
      </SettingRow>

      <SettingRow
        label="Hooks"
        description={
          <SettingDescription
            text="Execute commands at specific points in Codex's lifecycle, defined in .codex/hooks.json or config.toml. Review them with /hooks inside a session"
            docsUrl="https://learn.chatgpt.com/docs/hooks"
          />
        }
        noBorder
      >
        <span />
      </SettingRow>

      {/* Permissions */}
      <Text className="mb-2 block border-gray-6 border-t pt-4 font-medium text-sm">
        Permissions
      </Text>

      <SettingRow
        label="Claude permission rules"
        description="Tool permissions from your Claude settings. Allowed tools run without prompting. Denied tools are always blocked. Codex keeps its own rules in config.toml"
      >
        <CopyableCommand command="claude config" />
      </SettingRow>

      <PermissionsSettings />

      <SettingRow
        label="Allow bypass permissions mode"
        description="Adds bypass permissions to the mode menu so you can pick it per session. Sessions keep asking for approval until you pick it. This also unlocks Full access in Codex"
        noBorder
      >
        <Switch
          checked={allowBypassPermissions}
          onCheckedChange={handleBypassPermissionsChange}
          size="1"
          color="red"
        />
      </SettingRow>
      {allowBypassPermissions && (
        <Callout.Root size="1" color="red" mb="3">
          <Callout.Icon>
            <Warning weight="fill" />
          </Callout.Icon>
          <Callout.Text>
            Bypass permissions, and Full access in Codex, are now available in
            the mode menu in the prompt input. Pick one per session when you
            want that session to run shell commands, file edits and web requests
            without approval. Other sessions are unaffected.
          </Callout.Text>
        </Callout.Root>
      )}

      <AlertDialog.Root
        open={showBypassWarning}
        onOpenChange={setShowBypassWarning}
      >
        <AlertDialog.Content maxWidth="500px">
          <AlertDialog.Title color="red">
            <Flex align="center" gap="2">
              <Warning size={20} weight="fill" color="var(--red-9)" />
              <Text color="red" className="font-bold">
                Allow bypass permissions mode
              </Text>
            </Flex>
          </AlertDialog.Title>
          <AlertDialog.Description className="text-sm">
            <Flex direction="column" gap="3">
              <Text>
                This makes bypass permissions selectable in the mode menu. It
                does not turn it on for your tasks. Each session keeps its
                current mode until you pick bypass for it.
              </Text>
              <Text color="red" className="font-medium">
                A session running in bypass mode executes every action without
                asking, including shell commands, file edits, web requests and
                any installed MCP tools.
              </Text>
              <Text>
                Pick it for sandboxed environments (containers or VMs) with
                restricted network access that can be easily restored.
              </Text>
              <Text className="font-medium">
                By proceeding, you accept all responsibility for actions taken
                in sessions you run with bypass.
              </Text>
            </Flex>
          </AlertDialog.Description>
          <Flex gap="3" mt="4" justify="end">
            <AlertDialog.Cancel>
              <Button variant="soft" color="gray">
                Cancel
              </Button>
            </AlertDialog.Cancel>
            <AlertDialog.Action>
              <Button
                variant="solid"
                color="red"
                onClick={handleConfirmBypassPermissions}
              >
                Allow bypass mode
              </Button>
            </AlertDialog.Action>
          </Flex>
        </AlertDialog.Content>
      </AlertDialog.Root>
    </Flex>
  );
}
