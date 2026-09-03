import {
  FileTextIcon,
  GitBranchIcon,
  SparkleIcon,
} from "@phosphor-icons/react";
import {
  ContextWikiUnavailableError,
  FolderInstructionsConflictError,
} from "@posthog/api-client/posthog-client";
import { buildContextSaveProps } from "@posthog/core/canvas/canvasAnalytics";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Button as QuillButton,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type { TaskChannel } from "@posthog/shared/domain-types";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { ChannelHeader } from "@posthog/ui/features/canvas/components/ChannelHeader";
import { CreateChannelModal } from "@posthog/ui/features/canvas/components/CreateChannelModal";
import { channelPageIcon } from "@posthog/ui/features/canvas/components/channelPages";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import {
  useFolderInstructions,
  useFolderInstructionsMutations,
  useFolderInstructionsVersions,
} from "@posthog/ui/features/canvas/hooks/useFolderInstructions";
import {
  useTaskChannels,
  useUpdateTaskChannelRepositories,
} from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { ContextWikiPagePane } from "@posthog/ui/features/context-wiki/components/ContextWikiPagePane";
import { useChannelContextWikiPage } from "@posthog/ui/features/context-wiki/hooks/useContextWiki";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { useContextLayerFlag } from "@posthog/ui/features/feature-flags/useContextLayerFlag";
import { RepositoriesField } from "@posthog/ui/features/integrations/components/RepositoriesField";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import {
  PageHeader,
  PageHeaderActions,
  PageHeaderChip,
  PageHeaderDescription,
  PageHeaderHeading,
  PageHeaderTitle,
  PageHeaderTitleRow,
} from "@posthog/ui/primitives/PageHeader";
import { navigateToSpacesContext } from "@posthog/ui/router/navigationBridge";
import { track } from "@posthog/ui/shell/analytics";
import {
  Box,
  Button,
  Callout,
  Flex,
  ScrollArea,
  SegmentedControl,
  Select,
  Spinner,
  Text,
  TextArea,
} from "@radix-ui/themes";
import { useEffect, useMemo, useState } from "react";

type Mode = "rendered" | "edit";

const CHANNEL_EMPTY_TEMPLATE =
  "# Channel context\n\nDescribe what lives here.\n";
const SPACE_EMPTY_TEMPLATE = "# Space context\n\nDescribe what lives here.\n";

interface WebsiteContextProps {
  channelId: string;
}

export function WebsiteContext({ channelId }: WebsiteContextProps) {
  const contextLayerEnabled = useContextLayerFlag();
  const wikiPage = useChannelContextWikiPage(channelId, contextLayerEnabled);

  if (contextLayerEnabled && wikiPage.isLoading) {
    return (
      <Flex align="center" justify="center" className="h-full">
        <Spinner size="2" />
      </Flex>
    );
  }

  if (contextLayerEnabled && wikiPage.data) {
    return (
      <WikiWebsiteContext channelId={channelId} path={wikiPage.data.path} />
    );
  }

  if (contextLayerEnabled && wikiPage.error) {
    const unavailable = wikiPage.error instanceof ContextWikiUnavailableError;
    return (
      <Empty>
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <FileTextIcon size={28} />
          </EmptyMedia>
          <EmptyTitle>
            {unavailable
              ? "Context wiki unavailable"
              : "Could not load context"}
          </EmptyTitle>
          <EmptyDescription>{wikiPage.error.message}</EmptyDescription>
        </EmptyHeader>
        {!unavailable ? (
          <EmptyContent>
            <QuillButton variant="outline" onClick={() => wikiPage.refetch()}>
              Try again
            </QuillButton>
          </EmptyContent>
        ) : null}
      </Empty>
    );
  }

  return <LegacyWebsiteContext channelId={channelId} />;
}

function WikiWebsiteContext({
  channelId,
  path,
}: {
  channelId: string;
  path: string;
}) {
  const spacesLayout = useChannelsLayout();
  const { channels: taskChannels } = useTaskChannels();
  const taskChannel = taskChannels.find((channel) => channel.id === channelId);
  const headerContent = useMemo(
    () => <ChannelHeader channelId={channelId} page="context" />,
    [channelId],
  );
  useSetHeaderContent(headerContent);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {spacesLayout ? (
        <PageHeader>
          <PageHeaderHeading>
            <PageHeaderTitleRow>
              <PageHeaderTitle>Context</PageHeaderTitle>
              <PageHeaderChip icon={channelPageIcon("context", { size: 12 })}>
                {path}
              </PageHeaderChip>
            </PageHeaderTitleRow>
            <PageHeaderDescription>
              Agents working in this space can find this page in the shared
              context wiki.
            </PageHeaderDescription>
          </PageHeaderHeading>
          <PageHeaderActions>
            <QuillButton
              variant="outline"
              size="sm"
              onClick={() => navigateToSpacesContext(path)}
            >
              Open in context wiki
            </QuillButton>
          </PageHeaderActions>
        </PageHeader>
      ) : null}
      {spacesLayout && taskChannel ? (
        <SpaceRepositories channel={taskChannel} />
      ) : null}
      <ContextWikiPagePane key={path} path={path} />
    </div>
  );
}

function LegacyWebsiteContext({ channelId }: WebsiteContextProps) {
  const spacesLayout = useChannelsLayout();
  const emptyTemplate = spacesLayout
    ? SPACE_EMPTY_TEMPLATE
    : CHANNEL_EMPTY_TEMPLATE;
  const { channels } = useChannels();
  const channelName =
    channels.find((c) => c.id === channelId)?.name ??
    (spacesLayout ? "Space" : "Channel");
  const { channels: taskChannels } = useTaskChannels();
  const taskChannel = taskChannels.find((channel) => channel.id === channelId);

  const {
    data: latest,
    isLoading: isLoadingLatest,
    isFetching: isFetchingLatest,
    error: latestError,
  } = useFolderInstructions(channelId, { pollWhileEmpty: true });

  const { data: versions = [], isLoading: isLoadingVersions } =
    useFolderInstructionsVersions(channelId);

  const { publish, isPublishing, publishError } =
    useFolderInstructionsMutations(channelId);

  const [mode, setMode] = useState<Mode>("rendered");
  const [draft, setDraft] = useState("");
  const [hasDraft, setHasDraft] = useState(false);

  const hasInstructions = (latest?.content ?? "").trim().length > 0;

  useEffect(() => {
    if (hasDraft) return;
    setDraft(latest?.content ?? "");
  }, [latest?.content, hasDraft]);

  const headerContent = useMemo(
    () => <ChannelHeader channelId={channelId} page="context" />,
    [channelId],
  );
  useSetHeaderContent(headerContent);

  const onSave = async () => {
    try {
      await publish({
        content: draft,
        baseVersion: latest?.version ?? 0,
      });
      track(
        ANALYTICS_EVENTS.CONTEXT_ACTION,
        buildContextSaveProps({ channelId, hasInstructions, success: true }),
      );
      setHasDraft(false);
      setMode("rendered");
    } catch {
      track(
        ANALYTICS_EVENTS.CONTEXT_ACTION,
        buildContextSaveProps({ channelId, hasInstructions, success: false }),
      );
    }
  };

  const isConflict = publishError instanceof FolderInstructionsConflictError;

  const [selectedVersionNumber, setSelectedVersionNumber] = useState<
    number | null
  >(null);

  const selectedVersion = useMemo(() => {
    if (selectedVersionNumber == null) return null;
    return versions.find((v) => v.version === selectedVersionNumber) ?? null;
  }, [selectedVersionNumber, versions]);

  if (isLoadingLatest) {
    return (
      <Flex align="center" justify="center" className="h-full">
        <Spinner size="2" />
      </Flex>
    );
  }

  if (latestError) {
    return (
      <Flex direction="column" gap="3" p="4">
        <Callout.Root color="red" size="1">
          <Callout.Text>
            Failed to load channel instructions: {latestError.message}
          </Callout.Text>
        </Callout.Root>
      </Flex>
    );
  }

  const renderedContent = latest?.content ?? "";

  return (
    <Flex direction="column" height="100%" className="overflow-hidden">
      {/* The shared page header ships with the spaces layout; without it the
          page opens straight onto its mode toolbar as it always has. */}
      {spacesLayout && (
        <PageHeader>
          <PageHeaderHeading>
            <PageHeaderTitleRow>
              <PageHeaderTitle>Context</PageHeaderTitle>
              {latest?.version != null && (
                <PageHeaderChip icon={channelPageIcon("context", { size: 12 })}>
                  v{latest.version}
                </PageHeaderChip>
              )}
            </PageHeaderTitleRow>
            <PageHeaderDescription>
              Background every agent working in this{" "}
              {spacesLayout ? "space" : "channel"} reads before it starts — what
              lives here, who cares about it, and how to work on it.
            </PageHeaderDescription>
          </PageHeaderHeading>
        </PageHeader>
      )}
      {spacesLayout && taskChannel ? (
        <SpaceRepositories channel={taskChannel} />
      ) : null}
      <Flex
        align="center"
        justify="between"
        gap="3"
        px="4"
        py="2"
        className="shrink-0 border-b border-b-(--gray-5)"
      >
        <Flex align="center" gap="3">
          <SegmentedControl.Root
            value={mode}
            onValueChange={(value) => setMode(value as Mode)}
            size="1"
          >
            <SegmentedControl.Item value="rendered">
              Rendered
            </SegmentedControl.Item>
            <SegmentedControl.Item value="edit">Edit</SegmentedControl.Item>
          </SegmentedControl.Root>

          {/* Background-refetch indicator: the initial load uses the full-screen
              spinner below; this only fires on revalidations (every mount, plus
              after publish/delete invalidations) so the user knows the view is
              live and not just stale cache. */}
          {isFetchingLatest && !isLoadingLatest ? (
            <Flex align="center" gap="1">
              <Spinner size="1" />
              <Text className="text-[12px] text-gray-10">Refreshing…</Text>
            </Flex>
          ) : null}

          {versions.length > 0 ? (
            <Select.Root
              size="1"
              value={
                selectedVersionNumber != null
                  ? String(selectedVersionNumber)
                  : "latest"
              }
              onValueChange={(value) => {
                if (value === "latest") {
                  setSelectedVersionNumber(null);
                } else {
                  setSelectedVersionNumber(Number(value));
                  setMode("rendered");
                }
              }}
              disabled={isLoadingVersions}
            >
              <Select.Trigger />
              <Select.Content>
                <Select.Item value="latest">
                  Latest (v{latest?.version ?? "—"})
                </Select.Item>
                {versions
                  .filter((v) => v.version !== latest?.version)
                  .map((v) => (
                    <Select.Item key={v.version} value={String(v.version)}>
                      v{v.version} · {formatTimestamp(v.created_at)}
                    </Select.Item>
                  ))}
              </Select.Content>
            </Select.Root>
          ) : null}
        </Flex>

        {mode === "edit" ? (
          <Flex align="center" gap="2">
            {hasDraft ? (
              <Button
                size="1"
                variant="soft"
                color="gray"
                onClick={() => {
                  setDraft(latest?.content ?? "");
                  setHasDraft(false);
                }}
                disabled={isPublishing}
              >
                Discard
              </Button>
            ) : null}
            <Button
              size="1"
              variant="solid"
              onClick={onSave}
              disabled={
                isPublishing ||
                (hasInstructions ? !hasDraft : draft.trim().length === 0)
              }
            >
              {isPublishing ? <Spinner size="1" /> : null}
              Save new version
            </Button>
          </Flex>
        ) : null}
      </Flex>

      {publishError ? (
        <Box px="4" pt="3">
          <Callout.Root color={isConflict ? "amber" : "red"} size="1">
            <Callout.Text>
              {isConflict
                ? "Someone else saved a newer version. Reload to merge your changes."
                : `Save failed: ${publishError.message}`}
            </Callout.Text>
          </Callout.Root>
        </Box>
      ) : null}

      {!selectedVersion && mode === "edit" ? (
        <Box p="4" className="flex min-h-0 flex-1">
          <TextArea
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value);
              setHasDraft(true);
            }}
            size="2"
            placeholder={
              spacesLayout
                ? "# Space context\n\nWrite markdown describing this space…"
                : "# Channel context\n\nWrite markdown describing this channel…"
            }
            className="min-h-0 flex-1 font-[var(--code-font-family)]"
          />
        </Box>
      ) : (
        <ScrollArea
          type="auto"
          scrollbars="vertical"
          className="scroll-area-constrain-width min-h-0 flex-1"
        >
          <Box p="4">
            {selectedVersion ? (
              <Callout.Root color="gray" size="1">
                <Callout.Text>
                  Viewing v{selectedVersion.version} metadata. Past content is
                  not fetched today — switch to "Latest" to read or edit current
                  content.
                </Callout.Text>
              </Callout.Root>
            ) : hasInstructions ? (
              <Box className="text-[13px]">
                <MarkdownRenderer content={renderedContent} />
              </Box>
            ) : (
              <EmptyState
                channelId={channelId}
                channelName={channelName}
                onCreate={() => {
                  setDraft(emptyTemplate);
                  setHasDraft(true);
                  setMode("edit");
                }}
              />
            )}
          </Box>
        </ScrollArea>
      )}
    </Flex>
  );
}

function SpaceRepositories({ channel }: { channel: TaskChannel }) {
  const update = useUpdateTaskChannelRepositories();
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({ client });
  const canEdit = currentUser?.id === channel.created_by?.id;

  return (
    <div className="flex shrink-0 flex-col gap-2 border-b border-b-(--gray-5) px-4 py-3">
      <div className="flex items-center gap-2">
        <GitBranchIcon size={15} className="text-muted-foreground" />
        <span className="font-medium text-[13px]">Repositories</span>
        {update.isPending ? (
          <Spinner size="1" />
        ) : update.error ? (
          <span className="text-[12px] text-red-11">
            Couldn't save. Try again.
          </span>
        ) : null}
      </div>
      <RepositoriesField
        selected={channel.repositories ?? []}
        integrationId={channel.github_integration ?? null}
        disabled={!canEdit || update.isPending}
        onChange={(repositories, githubIntegration) =>
          update.mutate({
            channelId: channel.id,
            githubIntegration,
            repositories,
          })
        }
      />
    </div>
  );
}

function EmptyState({
  channelId,
  channelName,
  onCreate,
}: {
  channelId: string;
  channelName: string;
  onCreate: () => void;
}) {
  return (
    <Empty>
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <FileTextIcon size={28} />
        </EmptyMedia>
        <EmptyTitle>No CONTEXT.md yet</EmptyTitle>
        <EmptyDescription>
          CONTEXT.md tells agents the specific details they need to know when
          working in <strong>{channelName}</strong> — conventions, gotchas, key
          files, and anything else that isn't obvious from the code.
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Flex align="center" gap="3">
          <QuillButton variant="primary" size="default" onClick={onCreate}>
            Write it myself
          </QuillButton>
          <GenerateWithAgent channelId={channelId} channelName={channelName} />
        </Flex>
      </EmptyContent>
    </Empty>
  );
}

function GenerateWithAgent({
  channelId,
  channelName,
}: {
  channelId: string;
  channelName: string;
}) {
  const [dialogOpen, setDialogOpen] = useState(false);

  return (
    <>
      <QuillButton
        variant="outline"
        size="default"
        onClick={() => setDialogOpen(true)}
      >
        <SparkleIcon size={14} />
        Build with agent
      </QuillButton>
      <CreateChannelModal
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        existingContext={{ channelId, channelName }}
      />
    </>
  );
}

function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}
