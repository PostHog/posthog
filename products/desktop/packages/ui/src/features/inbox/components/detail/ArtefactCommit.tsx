import { CaretDownIcon, CaretRightIcon } from "@phosphor-icons/react";
import { inboxReportKeys } from "@posthog/core/inbox/inboxQuery";
import type { CommitContent } from "@posthog/shared/types";
import { DiffBlock } from "@posthog/ui/features/inbox/components/detail/DiffBlock";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { Box, Flex, Spinner, Text } from "@radix-ui/themes";
import { useState } from "react";

/**
 * Renders a `commit` artefact: commit metadata plus a collapsible diff of the commit against
 * its parent, fetched lazily (on first expand) from the team's GitHub integration.
 * `hideDiff` drops the diff toggle — used on the PR detail, where the main
 * column already shows every changed file.
 */
export function ArtefactCommit({
  reportId,
  artefactId,
  content,
  hideDiff = false,
}: {
  reportId: string;
  artefactId: string;
  content: CommitContent;
  hideDiff?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);

  const diffQuery = useAuthenticatedQuery(
    [...inboxReportKeys.artefacts(reportId), artefactId, "diff"],
    (client) => client.getCommitDiff(reportId, artefactId),
    // Only fetch once expanded; a commit's diff is immutable.
    { enabled: expanded, staleTime: 5 * 60_000, retry: false },
  );

  return (
    <Box>
      <Text className="block text-(--gray-12) text-[12px]">
        {content.message}
      </Text>
      <Text className="block font-mono text-(--gray-10) text-[11px]">
        {content.commit_sha.slice(0, 12)} · {content.repository}@
        {content.branch}
      </Text>
      {content.note?.trim() ? (
        <Text className="block text-(--gray-11) text-[12px]">
          {content.note}
        </Text>
      ) : null}

      {!hideDiff && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="-mx-1 mt-1.5 flex items-center gap-1 rounded-md px-1 py-0.5 text-(--gray-11) text-[12px] transition-colors hover:bg-(--gray-3) hover:text-(--gray-12)"
        >
          {expanded ? (
            <CaretDownIcon size={12} className="shrink-0" />
          ) : (
            <CaretRightIcon size={12} className="shrink-0" />
          )}
          {expanded ? "Hide diff" : "View diff"}
        </button>
      )}

      {expanded && !hideDiff ? (
        <Box className="mt-1.5">
          {diffQuery.isLoading ? (
            <Flex
              align="center"
              gap="2"
              className="text-(--gray-10) text-[12px]"
            >
              <Spinner size="1" />
              Fetching diff…
            </Flex>
          ) : diffQuery.isError ? (
            <Text className="block text-(--red-11) text-[12px]">
              {diffQuery.error instanceof Error
                ? diffQuery.error.message
                : "Couldn’t load the diff."}
            </Text>
          ) : diffQuery.data?.diff.trim() ? (
            <>
              <DiffBlock diff={diffQuery.data.diff} />
              {diffQuery.data.truncated ? (
                <Text className="mt-1 block text-(--gray-10) text-[11px]">
                  Diff truncated — too large to display in full.
                </Text>
              ) : null}
            </>
          ) : (
            <Text className="block text-(--gray-10) text-[12px]">
              No changes recorded for this commit.
            </Text>
          )}
        </Box>
      ) : null}
    </Box>
  );
}
