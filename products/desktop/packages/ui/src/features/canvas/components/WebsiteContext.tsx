import {
  FileTextIcon,
  GitBranchIcon,
  GithubLogoIcon,
  SparkleIcon,
  XIcon,
} from "@phosphor-icons/react";
import { FolderInstructionsConflictError } from "@posthog/api-client/posthog-client";
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
  useBackendChannel,
  useUpdateTaskChannelRepositories,
} from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { GitHubRepoPicker } from "@posthog/ui/features/folder-picker/GitHubRepoPicker";
import { useRepositoryIntegration } from "@posthog/ui/features/integrations/useIntegrations";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import {
  PageHeader,
  PageHeaderChip,
  PageHeaderDescription,
  PageHeaderHeading,
  PageHeaderTitle,
  PageHeaderTitleRow,
} from "@posthog/ui/primitives/PageHeader";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
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

// Initial markdown shown when a folder has no instructions yet — gives both
// humans and agents a structural starting point instead of a blank screen.
const CHANNEL_EMPTY_TEMPLATE =
  "# Channel context\n\nDescribe what lives here.\n";
const SPACE_EMPTY_TEMPLATE = "# Space context\n\nDescribe what lives here.\n";

interface WebsiteContextProps {
  channelId: string;
}

export function WebsiteContext({ channelId }: WebsiteContextProps) {
  const spacesLayout = useChannelsLayout();
  const emptyTemplate = spacesLayout
    ? SPACE_EMPTY_TEMPLATE
    : CHANNEL_EMPTY_TEMPLATE;
  // Channel name for the empty-state copy (the header reads its own).
  const { channels } = useChannels();
  const channelName =
    channels.find((c) => c.id === channelId)?.name ??
    (spacesLayout ? "Space" : "Channel");
  const { channel: backendChannel } = useBackendChannel(channelName);

  const {
    data: latest,
    isLoading: isLoadingLatest,
    isFetching: isFetchingLatest,
    error: latestError,
    // Poll while empty so an agent's CONTEXT.md publish (mid plan-session, via
    // the MCP) replaces the empty state without a manual reload.
  } = useFolderInstructions(channelId, { pollWhileEmpty: true });

  const { data: versions = [], isLoading: isLoadingVersions } =
    useFolderInstructionsVersions(channelId);

  const { publish, isPublishing, publishError } =
    useFolderInstructionsMutations(channelId);

  const [mode, setMode] = useState<Mode>("rendered");
  const [draft, setDraft] = useState("");
  const [hasDraft, setHasDraft] = useState(false);

  const hasInstructions = (latest?.content ?? "").trim().length > 0;

  // Seed the editor draft from the latest content the first time we land on
  // edit mode (or whenever latest changes while we're not actively editing).
  // We don't blow away an in-flight edit just because the cache refetched.
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
        // base_version=0 signals "no prior version" to the optimistic
        // concurrency check; otherwise we send the version we started from.
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
      // Errors surface through `publishError` below; nothing to do here.
    }
  };

  const isConflict = publishError instanceof FolderInstructionsConflictError;

  // Allow inspecting an older version read-only. When `null`, we're showing
  // either the latest (rendered/edit) or the empty state.
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(
    null,
  );

  // Picking a past version forces rendered mode and shows that version's
  // metadata; we don't currently fetch the historical content body, so the
  // viewer falls back to "Open latest in editor" when there is no body.
  // (Backend exposes content only via the `latest` endpoint today.)
  const selectedVersion = useMemo(() => {
    if (!selectedVersionId) return null;
    return versions.find((v) => v.id === selectedVersionId) ?? null;
  }, [selectedVersionId, versions]);

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
            Failed to load folder instructions: {latestError.message}
          </Callout.Text>
        </Callout.Root>
      </Flex>
    );
  }

  // Treat `null` (404: never published), `undefined` (query disabled), AND a
  // row with whitespace-only content as "no instructions" so we render the
  // empty state — otherwise MarkdownRenderer paints an invisible empty block
  // and the page looks blank.
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
            </PageHeaderTitleRow>
            <PageHeaderDescription>
              Background every agent working in this{" "}
              {spacesLayout ? "space" : "channel"} reads before it starts — what
              lives here, who cares about it, and how to work on it.
            </PageHeaderDescription>
          </PageHeaderHeading>
        </PageHeader>
      )}
      <div className="flex min-h-0 w-full flex-1 flex-col gap-4 px-6 py-4">
        {spacesLayout && backendChannel ? (
          <>
            <SpaceRepositories channel={backendChannel} />
            <div className="border-gray-5 border-t" />
          </>
        ) : null}

        <Flex align="center" justify="between" gap="3" wrap="wrap">
          <Flex align="center" gap="2">
            <FileTextIcon size={15} className="text-gray-11" />
            <Text size="2" weight="medium">
              CONTEXT.md
            </Text>
            {latest?.version != null && (
              <PageHeaderChip icon={channelPageIcon("context", { size: 12 })}>
                v{latest.version}
              </PageHeaderChip>
            )}
            {/* Background-refetch indicator: the initial load uses the
                full-screen spinner; this only fires on revalidations so the
                user knows the view is live, not stale cache. */}
            {isFetchingLatest && !isLoadingLatest ? (
              <Flex align="center" gap="1">
                <Spinner size="1" />
                <Text className="text-[12px] text-gray-10">Refreshing…</Text>
              </Flex>
            ) : null}
          </Flex>
          <Flex align="center" gap="2">
            {versions.length > 0 ? (
              <Select.Root
                size="1"
                value={selectedVersionId ?? "latest"}
                onValueChange={(value) => {
                  if (value === "latest") {
                    setSelectedVersionId(null);
                  } else {
                    setSelectedVersionId(value);
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
                    .filter((v) => !v.is_latest)
                    .map((v) => (
                      <Select.Item key={v.id} value={v.id}>
                        v{v.version} · {formatTimestamp(v.created_at)}
                      </Select.Item>
                    ))}
                </Select.Content>
              </Select.Root>
            ) : null}
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
            {mode === "edit" ? (
              <>
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
              </>
            ) : null}
          </Flex>
        </Flex>

        {publishError ? (
          <Callout.Root color={isConflict ? "amber" : "red"} size="1">
            <Callout.Text>
              {isConflict
                ? "Someone else saved a newer version. Reload to merge your changes."
                : `Save failed: ${publishError.message}`}
            </Callout.Text>
          </Callout.Root>
        ) : null}

        {selectedVersion ? (
          <Callout.Root color="gray" size="1">
            <Callout.Text>
              Viewing v{selectedVersion.version} metadata. Past content is not
              fetched today — switch to "Latest" to read or edit current
              content.
            </Callout.Text>
          </Callout.Root>
        ) : mode === "rendered" ? (
          hasInstructions ? (
            <ScrollArea
              type="auto"
              scrollbars="vertical"
              className="scroll-area-constrain-width min-h-0 flex-1"
            >
              <Box className="rounded-lg border border-gray-5 bg-gray-2 px-6 py-5 text-[13px]">
                <MarkdownRenderer content={renderedContent} />
              </Box>
            </ScrollArea>
          ) : (
            <Flex align="center" justify="center" className="min-h-0 flex-1">
              <EmptyState
                channelId={channelId}
                channelName={channelName}
                onCreate={() => {
                  setDraft(emptyTemplate);
                  setHasDraft(true);
                  setMode("edit");
                }}
              />
            </Flex>
          )
        ) : (
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
        )}
      </div>
    </Flex>
  );
}

const MAX_REPOSITORIES = 10;

// The space's repositories rendered as a subtle inline chip picker: a single
// row of removable chips with an inline "add" input, driven entirely by the
// quill Combobox. Selected repos must all belong to one GitHub integration,
// so the add list is scoped to the active integration once one is chosen.
// A single repository, rendered as a subtle tag. The leading GitHub glyph
// swaps to an X on hover so the whole chip is the remove target — no separate
// delete button crowding the tag (mirrors the message editor's attachments).
function RepoChip({
  repository,
  onRemove,
}: {
  repository: string;
  onRemove: () => void;
}) {
  return (
    <span className="group/chip inline-flex items-center gap-1 rounded-(--radius-1) bg-(--gray-a3) py-0.5 pr-2 pl-1.5 font-medium text-(--gray-11) text-[12px] transition-colors hover:bg-(--gray-a4)">
      <button
        type="button"
        aria-label={`Remove ${repository}`}
        className="relative inline-flex size-3.5 shrink-0 cursor-pointer items-center justify-center border-none bg-transparent p-0"
        onClick={onRemove}
      >
        <span className="pointer-events-none absolute inset-0 flex items-center justify-center opacity-100 transition-opacity duration-150 group-hover/chip:opacity-0 motion-reduce:transition-none">
          <GithubLogoIcon size={13} />
        </span>
        <span className="pointer-events-none absolute inset-0 flex items-center justify-center opacity-0 transition-opacity duration-150 group-hover/chip:opacity-100 motion-reduce:transition-none">
          <XIcon size={12} weight="bold" />
        </span>
      </button>
      <span className="max-w-[200px] truncate">{repository}</span>
    </span>
  );
}

// The space's connected repositories: a header row that matches the CONTEXT.md
// header, then a row of tag chips plus an on-demand picker to add more. Reads
// straight from the channel (the mutation applies each add/remove optimistically
// to the cache), so there's no local mirror and no Save button. Selected repos
// must share one GitHub integration, so the add list scopes to it.
function SpaceRepositories({ channel }: { channel: TaskChannel }) {
  const {
    repositories,
    getIntegrationIdForRepo,
    isLoadingRepos,
    isRefreshingRepos,
    refreshRepositories,
    hasGithubIntegration,
  } = useRepositoryIntegration();
  const update = useUpdateTaskChannelRepositories();

  const selected = channel.repositories ?? [];
  const integrationId = channel.github_integration ?? null;
  const atLimit = selected.length >= MAX_REPOSITORIES;

  const available = repositories.filter((repository) => {
    const repositoryIntegration = getIntegrationIdForRepo(repository);
    return (
      !selected.includes(repository) &&
      repositoryIntegration != null &&
      (integrationId === null || repositoryIntegration === integrationId)
    );
  });

  const save = (nextSelected: string[], nextIntegration: number | null) =>
    update.mutate({
      channelId: channel.id,
      githubIntegration: nextIntegration,
      repositories: nextSelected,
    });

  const addRepository = (repository: string | null) => {
    if (!repository || selected.includes(repository)) return;
    const repositoryIntegration = getIntegrationIdForRepo(repository);
    if (repositoryIntegration == null) return;
    save([...selected, repository], repositoryIntegration);
  };

  const removeRepository = (repository: string) => {
    const next = selected.filter((item) => item !== repository);
    save(next, next.length === 0 ? null : integrationId);
  };

  // When there's nothing to add, keep the button visible but disabled with a
  // reason, rather than the picker's own "No GitHub repos" dead-end state.
  const addDisabledReason = !hasGithubIntegration
    ? "Connect GitHub in settings to add repositories"
    : atLimit
      ? `You can add up to ${MAX_REPOSITORIES} repositories`
      : isLoadingRepos && available.length === 0
        ? "Loading repositories…"
        : available.length === 0
          ? "All accessible repositories are already added"
          : null;

  return (
    <Flex direction="column" gap="2">
      <Flex align="center" gap="2">
        <GitBranchIcon size={15} className="text-gray-11" />
        <Text size="2" weight="medium">
          Repositories
        </Text>
        {update.isPending ? (
          <Spinner size="1" />
        ) : update.error ? (
          <Text size="1" color="red">
            Couldn't save
          </Text>
        ) : null}
      </Flex>

      <Flex align="center" gap="2" wrap="wrap" className="min-h-7">
        {selected.map((repository) => (
          <RepoChip
            key={repository}
            repository={repository}
            onRemove={() => removeRepository(repository)}
          />
        ))}

        {addDisabledReason ? (
          <Tooltip content={addDisabledReason}>
            <span className="inline-flex">
              <QuillButton variant="outline" size="sm" disabled>
                <GithubLogoIcon size={14} />
                Add repository
              </QuillButton>
            </span>
          </Tooltip>
        ) : (
          <GitHubRepoPicker
            value={null}
            onChange={addRepository}
            repositories={available}
            isLoading={isLoadingRepos}
            isRefreshing={isRefreshingRepos}
            onRefresh={() => void refreshRepositories()}
            placeholder={selected.length > 0 ? "Add" : "Add a repository…"}
            size="1"
            // Multi-add strip: never auto-select the lone remaining repo, or
            // deleting down to one addable repo would immediately re-add it.
            autoSelectSingle={false}
          />
        )}
      </Flex>
    </Flex>
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

// Opens the describe-and-plan dialog for this (already-existing) context, which
// launches a plan-mode session that investigates PostHog + the repo and publishes
// CONTEXT.md via the MCP once the user approves the plan. Same flow as creating a
// context from scratch, minus the name field.
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

// `created_at` is an ISO timestamp; we render it as a short local string for
// the version dropdown. Falls back to the raw string if Date parsing fails.
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
