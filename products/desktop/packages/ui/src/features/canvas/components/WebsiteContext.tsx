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

// The anchor nav on the left of the spaces layout: one row per configurable
// section on this screen. Future sources (Slack channels, PostHog events, …)
// get a row here plus a section in the pane.
const NAV_SECTIONS = [
  {
    id: "context-md",
    label: "CONTEXT.md",
    icon: <FileTextIcon size={16} />,
  },
  {
    id: "repositories",
    label: "Repositories",
    icon: <GitBranchIcon size={16} />,
  },
];

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

  const sectionIds = useMemo(
    () =>
      spacesLayout && backendChannel
        ? ["context-md", "repositories"]
        : ["context-md"],
    [spacesLayout, backendChannel],
  );
  const [activeSection, setActiveSection] = useState("context-md");
  // If the repositories section vanishes (channel row still loading), fall
  // back to the document rather than an empty pane.
  const resolvedSection = sectionIds.includes(activeSection)
    ? activeSection
    : "context-md";

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
      <div className="flex min-h-0 flex-1">
        {sectionIds.length > 1 && (
          <nav
            aria-label="Context sections"
            className="w-52 shrink-0 overflow-y-auto border-gray-5 border-r py-3"
          >
            {NAV_SECTIONS.filter((section) =>
              sectionIds.includes(section.id),
            ).map((section) => (
              <button
                key={section.id}
                type="button"
                data-active={resolvedSection === section.id || undefined}
                onClick={() => setActiveSection(section.id)}
                className="flex w-full cursor-pointer items-center gap-2 border-0 bg-transparent px-4 py-1.5 text-left text-[13px] text-gray-11 transition-colors hover:bg-gray-3 data-[active]:bg-accent-4 data-[active]:text-gray-12"
              >
                <span className="text-gray-10">{section.icon}</span>
                <span>{section.label}</span>
              </button>
            ))}
          </nav>
        )}
        {resolvedSection === "context-md" ? (
          <div className="mx-auto flex min-h-0 w-full max-w-3xl flex-1 flex-col gap-3 px-6 py-5">
            <Flex align="center" justify="between" gap="3" wrap="wrap">
              <Flex align="center" gap="2">
                <FileTextIcon size={15} className="text-gray-11" />
                <Text size="2" weight="medium">
                  CONTEXT.md
                </Text>
                {latest?.version != null && (
                  <PageHeaderChip
                    icon={channelPageIcon("context", { size: 12 })}
                  >
                    v{latest.version}
                  </PageHeaderChip>
                )}
                {/* Background-refetch indicator: the initial load uses the
                      full-screen spinner; this only fires on revalidations so
                      the user knows the view is live, not stale cache. */}
                {isFetchingLatest && !isLoadingLatest ? (
                  <Flex align="center" gap="1">
                    <Spinner size="1" />
                    <Text className="text-[12px] text-gray-10">
                      Refreshing…
                    </Text>
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
                  <SegmentedControl.Item value="edit">
                    Edit
                  </SegmentedControl.Item>
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
                        (hasInstructions
                          ? !hasDraft
                          : draft.trim().length === 0)
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
                  Viewing v{selectedVersion.version} metadata. Past content is
                  not fetched today — switch to "Latest" to read or edit current
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
                <Flex
                  align="center"
                  justify="center"
                  className="min-h-0 flex-1"
                >
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
        ) : (
          <ScrollArea
            type="auto"
            scrollbars="vertical"
            className="scroll-area-constrain-width min-h-0 flex-1"
          >
            <div className="mx-auto w-full max-w-3xl px-6 py-5">
              {backendChannel ? (
                <SpaceRepositories channel={backendChannel} />
              ) : null}
            </div>
          </ScrollArea>
        )}
      </div>
    </Flex>
  );
}

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
  const [selected, setSelected] = useState(channel.repositories ?? []);
  const [integrationId, setIntegrationId] = useState<number | null>(
    channel.github_integration ?? null,
  );

  useEffect(() => {
    setSelected(channel.repositories ?? []);
    setIntegrationId(channel.github_integration ?? null);
  }, [channel.github_integration, channel.repositories]);

  const available = repositories.filter((repository) => {
    const repositoryIntegration = getIntegrationIdForRepo(repository);
    return (
      !selected.includes(repository) &&
      (integrationId === null || repositoryIntegration === integrationId)
    );
  });

  const addRepository = (repository: string | null) => {
    if (!repository) return;
    const repositoryIntegration = getIntegrationIdForRepo(repository);
    if (repositoryIntegration == null) return;
    setIntegrationId(repositoryIntegration);
    setSelected((current) => [...current, repository]);
  };

  const removeRepository = (repository: string) => {
    setSelected((current) => {
      const next = current.filter((item) => item !== repository);
      if (next.length === 0) setIntegrationId(null);
      return next;
    });
  };

  const changed =
    integrationId !== (channel.github_integration ?? null) ||
    selected.length !== (channel.repositories ?? []).length ||
    selected.some(
      (repository, index) => repository !== channel.repositories?.[index],
    );

  return (
    <Flex direction="column" gap="3">
      <Flex direction="column" gap="1">
        <Flex align="center" gap="2">
          <GitBranchIcon size={15} className="shrink-0 text-gray-11" />
          <Text size="2" weight="medium">
            Repositories
          </Text>
          {selected.length > 0 ? (
            <Text size="1" color="gray">
              {selected.length}/10
            </Text>
          ) : null}
        </Flex>
        <Text size="1" color="gray">
          New tasks in this space can work across these repositories.
        </Text>
      </Flex>
      <Flex direction="column" gap="3" maxWidth="480px">
        {selected.length > 0 ? (
          <div className="flex flex-col divide-y divide-(--gray-4) overflow-hidden rounded-md border border-gray-5">
            {selected.map((repository) => (
              <Flex key={repository} align="center" gap="2" px="3" py="2">
                <GithubLogoIcon size={14} className="shrink-0 text-gray-11" />
                <Text size="2" className="min-w-0 flex-1 truncate">
                  {repository}
                </Text>
                <Button
                  size="1"
                  variant="ghost"
                  color="gray"
                  aria-label={`Remove ${repository}`}
                  disabled={update.isPending}
                  onClick={() => removeRepository(repository)}
                >
                  <XIcon size={14} />
                </Button>
              </Flex>
            ))}
          </div>
        ) : null}
        <GitHubRepoPicker
          value={null}
          onChange={addRepository}
          repositories={available}
          isLoading={isLoadingRepos}
          isRefreshing={isRefreshingRepos}
          onRefresh={() => void refreshRepositories()}
          placeholder={
            hasGithubIntegration
              ? "Add repository..."
              : "Connect GitHub to add repositories"
          }
          size="1"
          disabled={
            !hasGithubIntegration || selected.length >= 10 || update.isPending
          }
        />
        {update.error ? (
          <Callout.Root color="red" size="1">
            <Callout.Text>
              Couldn't save repositories. Check your GitHub access and try
              again.
            </Callout.Text>
          </Callout.Root>
        ) : null}
        {changed ? (
          <Flex justify="end">
            <Button
              size="1"
              disabled={update.isPending}
              onClick={() =>
                update.mutate({
                  channelId: channel.id,
                  githubIntegration: integrationId,
                  repositories: selected,
                })
              }
            >
              {update.isPending ? <Spinner size="1" /> : null}
              Save repositories
            </Button>
          </Flex>
        ) : null}
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
