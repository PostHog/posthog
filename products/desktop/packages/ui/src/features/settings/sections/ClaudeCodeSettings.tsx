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

export function ClaudeCodeSettings() {
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
      {/* Extensions */}
      <Text className="mt-1 mb-2 font-medium text-sm">Extensions</Text>

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

      {/* Permissions */}
      <Text className="mb-2 block border-gray-6 border-t pt-4 font-medium text-sm">
        Permissions
      </Text>

      <SettingRow
        label="Permission rules"
        description="Tool permissions from your Claude settings. Allowed tools run without prompting. Denied tools are always blocked"
      >
        <CopyableCommand command="claude config" />
      </SettingRow>

      <PermissionsSettings />

      <SettingRow
        label="Bypass permissions"
        description="Skip all permission prompts. Claude will run bash commands, edit files, browse the web and use any tool without asking first"
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
            Bypass Permissions is enabled. All actions (shell commands, file
            edits, web requests) run without approval. Pick this mode from the
            mode menu in the prompt input per session.
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
                Enable bypass permissions
              </Text>
            </Flex>
          </AlertDialog.Title>
          <AlertDialog.Description className="text-sm">
            <Flex direction="column" gap="3">
              <Text color="red" className="font-medium">
                With bypass enabled, Claude will execute every action without
                asking -- including shell commands, file edits, web requests and
                any installed MCP tools.
              </Text>
              <Text>
                This mode is intended for sandboxed environments (containers or
                VMs) with restricted network access that can be easily restored.
              </Text>
              <Text className="font-medium">
                By proceeding, you accept all responsibility for actions taken
                while bypass is enabled.
              </Text>
            </Flex>
          </AlertDialog.Description>
          <Flex gap="3" mt="4" justify="end">
            <AlertDialog.Cancel>
              <Button variant="soft" color="gray">
                No, exit
              </Button>
            </AlertDialog.Cancel>
            <AlertDialog.Action>
              <Button
                variant="solid"
                color="red"
                onClick={handleConfirmBypassPermissions}
              >
                Yes, I accept
              </Button>
            </AlertDialog.Action>
          </Flex>
        </AlertDialog.Content>
      </AlertDialog.Root>
    </Flex>
  );
}
