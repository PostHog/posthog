import { FileTextIcon, GithubLogoIcon } from "@phosphor-icons/react";
import {
  ContextWikiUnavailableError,
  FolderInstructionsConflictError,
} from "@posthog/api-client/posthog-client";
import { buildContextSaveProps } from "@posthog/core/canvas/canvasAnalytics";
import { channelDisplayLabel } from "@posthog/core/canvas/channelName";
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
import {
  useChannelContextWikiPage,
  useCreateChannelContextWikiPage,
} from "@posthog/ui/features/context-wiki/hooks/useContextWiki";
import { SpacePagesSection } from "@posthog/ui/features/docs/components/SpacePagesSection";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { useContextLayerFlag } from "@posthog/ui/features/feature-flags/useContextLayerFlag";
import { RepositoriesField } from "@posthog/ui/features/integrations/components/RepositoriesField";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { AgentMark } from "@posthog/ui/primitives/AgentMark";
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
import type { ReactNode } from "react";
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
      <WikiWebsiteContext
        channelId={channelId}
        path={wikiPage.data.path}
        exists={wikiPage.data.exists !== false}
      />
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
  exists,
}: {
  channelId: string;
  path: string;
  /** False for a space added after the wiki was enabled: the page is only proposed. */
  exists: boolean;
}) {
  const spacesLayout = useChannelsLayout();
  const { channels: taskChannels } = useTaskChannels();
  const taskChannel = taskChannels.find((channel) => channel.id === channelId);
  const headerContent = useMemo(
    () => <ChannelHeader channelId={channelId} page="context" />,
    [channelId],
  );
  useSetHeaderContent(headerContent);

  if (!spacesLayout) {
    return exists ? (
      <ContextWikiPagePane key={path} path={path} />
    ) : (
      <StartWikiPage channelId={channelId} channelName={taskChannel?.name} />
    );
  }

  const spaceLabel = channelDisplayLabel(taskChannel?.name ?? "space");

  // One column, one scroll: the space's pages, what it works in, and the notes
  // it keeps, read as one page rather than three panes stacked on each other.
  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-[46rem] px-8 pt-8 pb-24">
          <h1 className="font-[540] text-(--gray-12) text-[30px] leading-[1.14] tracking-[-0.03em]">
            Context
          </h1>
          {/* The lede takes the column, so its line ends where the sections
              below it end rather than short of them. */}
          <p className="mt-2.5 text-(--gray-11) text-[15.2px] leading-[1.6]">
            What {spaceLabel} writes down: its pages, the repositories it works
            in, and the notes every agent reads first.
          </p>

          {/* Where the space works comes first and stays small: one line of
              repositories under the lede, before the things it writes. */}
          {taskChannel ? (
            <div className="mt-4">
              <SpaceRepositories channel={taskChannel} compact />
            </div>
          ) : null}

          <div className="mt-7 flex flex-col gap-9">
            <SpacePagesSection channelId={channelId} />
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * The notes a space does not have yet, when the wiki holds them.
 *
 * The page is written at the path the wiki reserved for this space, so the space
 * joins the wiki the same way every other one did.
 */
function StartWikiPage({
  channelId,
  channelName,
}: {
  channelId: string;
  channelName?: string;
}) {
  const create = useCreateChannelContextWikiPage(channelId);

  return (
    <Empty>
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <FileTextIcon size={28} />
        </EmptyMedia>
        <EmptyTitle>No notes yet</EmptyTitle>
        <EmptyDescription>
          Notes tell every agent what it needs to know to work in{" "}
          <strong>{channelName ?? "this space"}</strong>: the conventions, the
          key files, and anything else the code does not say on its own.
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <QuillButton
          variant="primary"
          size="default"
          loading={create.isPending}
          disabled={create.isPending}
          onClick={() => create.mutate()}
        >
          Start this page
        </QuillButton>
        {create.error ? (
          <span className="text-[12px] text-red-11">
            The page did not start. Try again.
          </span>
        ) : null}
      </EmptyContent>
    </Empty>
  );
}

/**
 * One measure for the page. Every band lines its contents up on the same column,
 * so the page reads as a page rather than as a stack of toolbars.
 */
function Band({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      <div className="mx-auto w-full max-w-[46rem] px-8">{children}</div>
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
        <Band className="shrink-0 pt-8 pb-1">
          <h1 className="font-[540] text-(--gray-12) text-[30px] leading-[1.14] tracking-[-0.03em]">
            {channelDisplayLabel(channelName)}
          </h1>
          <p className="mt-2.5 max-w-[34rem] text-(--gray-11) text-[15.2px] leading-[1.6]">
            What this space works on, and the notes every agent reads first.
          </p>
        </Band>
      )}
      {spacesLayout && taskChannel ? (
        <>
          <Band className="shrink-0 pt-7">
            <SpacePagesSection channelId={channelId} />
          </Band>
          <Band className="shrink-0 pt-7 pb-1">
            <SpaceRepositories channel={taskChannel} />
          </Band>
        </>
      ) : null}
      <Band className="shrink-0 pt-7">
        <div className="flex items-center justify-between gap-3 pb-2.5">
          <h2 className="font-semibold text-(--gray-12) text-[15px] tracking-[-0.008em]">
            Notes for agents
          </h2>
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
        </div>
      </Band>

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
        <Box className="mx-auto flex min-h-0 w-full max-w-[46rem] flex-1 px-8 py-3">
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
          <Box className="mx-auto w-full max-w-[46rem] px-8 pt-1 pb-10">
            {selectedVersion ? (
              <Callout.Root color="gray" size="1">
                <Callout.Text>
                  Viewing v{selectedVersion.version} metadata. Past content is
                  not fetched today. Switch to "Latest" to read or edit current
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

function SpaceRepositories({
  channel,
  compact = false,
}: {
  channel: TaskChannel;
  /** One line under the page's lede, instead of a section of its own. */
  compact?: boolean;
}) {
  const update = useUpdateTaskChannelRepositories();
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({ client });
  const canEdit = currentUser?.id === channel.created_by?.id;
  const repositories = channel.repositories ?? [];

  if (compact) {
    return (
      <div className="-mx-2 flex items-start gap-2 px-2 py-[7px]">
        <span className="mt-[7px] flex w-[14px] shrink-0 justify-center text-(--gray-8)">
          <GithubLogoIcon size={14} />
        </span>
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-2">
          {repositories.length === 0 ? (
            <span className="shrink-0 text-(--gray-10) text-[12.5px]">
              No repository yet
            </span>
          ) : null}
          <RepositoriesField
            selected={repositories}
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
          {update.isPending ? (
            <Spinner size="1" />
          ) : update.error ? (
            <span className="text-[12.5px] text-red-11">
              Couldn't save. Try again.
            </span>
          ) : null}
        </div>
      </div>
    );
  }

  return (
    <div className="flex shrink-0 flex-col">
      <div className="flex items-center gap-2 border-(--gray-4) border-b pb-2.5">
        <h2 className="font-semibold text-(--gray-12) text-[15px] tracking-[-0.008em]">
          Repositories
        </h2>
        {update.isPending ? (
          <Spinner size="1" />
        ) : update.error ? (
          <span className="text-[12px] text-red-11">
            Couldn't save. Try again.
          </span>
        ) : null}
      </div>
      {repositories.length === 0 ? (
        <p className="pt-3 text-(--gray-10) text-[13.5px] leading-relaxed">
          No repository yet, so a session here starts with nothing checked out.
        </p>
      ) : null}
      <div className="pt-3.5">
        <RepositoriesField
          selected={repositories}
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
        <EmptyTitle>No notes yet</EmptyTitle>
        <EmptyDescription>
          Notes tell every agent what it needs to know to work in{" "}
          <strong>{channelName}</strong>: the conventions, the key files, and
          anything else the code does not say on its own.
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
        <AgentMark size={14} />
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
