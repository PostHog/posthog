import { ArrowLeft, Warning } from "@phosphor-icons/react";
import { useAppView } from "@posthog/ui/router/useAppView";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import {
  Box,
  Button,
  Callout,
  Card,
  Code,
  Flex,
  Heading,
  Text,
} from "@radix-ui/themes";
import { useState } from "react";
import { useSetHeaderContent } from "../../hooks/useSetHeaderContent";
import { logger } from "../../shell/logger";
import { useFolders } from "../folders/useFolders";

const log = logger.scope("folder-settings");

export function FolderSettingsView() {
  useSetHeaderContent(null);

  const view = useAppView();
  const { folders, removeFolder } = useFolders();

  const folderId = view.type === "folder-settings" ? view.folderId : undefined;
  const folder = folders.find((f) => f.id === folderId);

  const [error, setError] = useState<string | null>(null);

  const handleRemoveFolder = async () => {
    if (!folderId) return;
    try {
      await removeFolder(folderId);
      openTaskInput();
    } catch (err) {
      log.error("Failed to remove folder:", err);
      setError(err instanceof Error ? err.message : "Failed to remove folder");
    }
  };

  if (!folder) {
    return (
      <Box height="100%" overflowY="auto">
        <Box p="6" style={{ margin: "0 auto" }} className="max-w-[600px]">
          <Flex direction="column" gap="4">
            <Callout.Root color="red">
              <Callout.Icon>
                <Warning />
              </Callout.Icon>
              <Callout.Text>Repository not found</Callout.Text>
            </Callout.Root>
            <Button
              variant="soft"
              size="2"
              onClick={() => openTaskInput()}
              className="self-start"
            >
              <ArrowLeft size={16} />
              Back to home
            </Button>
          </Flex>
        </Box>
      </Box>
    );
  }

  // When folder doesn't exist, show message to restore or remove
  if (!folder.exists) {
    return (
      <Box height="100%" overflowY="auto">
        <Box p="6" style={{ margin: "0 auto" }} className="max-w-[600px]">
          <Flex direction="column" gap="6">
            <Flex direction="column" gap="2">
              <Heading className="text-lg leading-6.5">
                Repository Not Found
              </Heading>
              <Text color="gray" className="text-[13px]">
                {folder.name}
              </Text>
            </Flex>

            <Callout.Root color="amber">
              <Callout.Icon>
                <Warning />
              </Callout.Icon>
              <Callout.Text>
                <Flex direction="column" gap="1">
                  <Text className="font-medium">
                    The repository folder could not be found
                  </Text>
                  <Text className="text-[13px]">
                    The folder at <Code>{folder.path}</Code> no longer exists or
                    has been moved.
                  </Text>
                </Flex>
              </Callout.Text>
            </Callout.Root>

            {error && (
              <Callout.Root color="red">
                <Callout.Text>{error}</Callout.Text>
              </Callout.Root>
            )}

            <Card>
              <Flex direction="column" gap="4">
                <Flex direction="column" gap="2">
                  <Text className="font-medium text-[13px]">
                    Option 1: Restore the folder
                  </Text>
                  <Text color="gray" className="text-[13px]">
                    Move or restore the repository folder back to its original
                    location:
                  </Text>
                  <Code className="text-[13px]">{folder.path}</Code>
                </Flex>
              </Flex>
            </Card>

            <Card>
              <Flex direction="column" gap="4">
                <Flex direction="column" gap="2">
                  <Text className="font-medium text-[13px]">
                    Option 2: Remove the repository
                  </Text>
                  <Text color="gray" className="text-[13px]">
                    This will remove the repository from PostHog, including all
                    associated tasks and their workspaces. This action cannot be
                    undone.
                  </Text>
                </Flex>
                <Button
                  variant="soft"
                  color="red"
                  size="1"
                  onClick={handleRemoveFolder}
                  className="self-start"
                >
                  Remove repository
                </Button>
              </Flex>
            </Card>

            <Button
              variant="soft"
              size="2"
              onClick={() => openTaskInput()}
              className="self-start"
            >
              <ArrowLeft size={16} />
              Back to home
            </Button>
          </Flex>
        </Box>
      </Box>
    );
  }

  // Normal settings view when folder exists
  return (
    <Box height="100%" overflowY="auto">
      <Box p="6" style={{ margin: "0 auto" }} className="max-w-[600px]">
        <Flex direction="column" gap="6">
          <Flex direction="column" gap="2">
            <Heading className="text-lg leading-6.5">
              Repository Settings
            </Heading>
            <Text color="gray" className="text-[13px]">
              Manage settings for {folder.name}
            </Text>
          </Flex>

          {error && (
            <Callout.Root color="red">
              <Callout.Text>{error}</Callout.Text>
            </Callout.Root>
          )}

          <Flex direction="column" gap="3">
            <Heading className="text-base">Location</Heading>
            <Card>
              <Flex direction="column" gap="2">
                <Text className="font-medium text-[13px]">Root path</Text>
                <Code className="text-[13px]">{folder.path}</Code>
              </Flex>
            </Card>
          </Flex>

          <Box className="border-gray-6 border-t" />

          <Flex direction="column" gap="3">
            <Heading className="text-base">Danger zone</Heading>
            <Card>
              <Flex direction="column" gap="4">
                <Flex direction="column" gap="2">
                  <Text className="font-medium text-[13px]">
                    Remove repository
                  </Text>
                  <Text color="gray" className="text-[13px]">
                    This will remove the repository from PostHog, including all
                    associated tasks and their workspaces. This action cannot be
                    undone.
                  </Text>
                </Flex>
                <Button
                  variant="soft"
                  color="red"
                  size="1"
                  onClick={handleRemoveFolder}
                  className="self-start"
                >
                  Remove repository
                </Button>
              </Flex>
            </Card>
          </Flex>
        </Flex>
      </Box>
    </Box>
  );
}
