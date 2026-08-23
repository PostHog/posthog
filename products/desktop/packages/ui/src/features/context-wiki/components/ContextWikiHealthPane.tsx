import { WarningCircleIcon } from "@phosphor-icons/react";
import type { ContextWikiHealthFinding } from "@posthog/api-client/posthog-client";
import {
  Button,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Heading,
  Spinner,
  Text,
} from "@posthog/quill";
import { useMemo } from "react";
import { useContextWikiHealthReport } from "../hooks/useContextWiki";

export function ContextWikiHealthPane({
  onOpenPage,
}: {
  onOpenPage: (path: string) => void;
}) {
  const { data, isLoading, error, refetch } = useContextWikiHealthReport();
  const groups = useMemo(() => groupFindings(data?.findings ?? []), [data]);

  if (isLoading) {
    return <Spinner className="m-auto" />;
  }
  if (error) {
    return (
      <Empty>
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <WarningCircleIcon />
          </EmptyMedia>
          <EmptyTitle>Couldn't load wiki health</EmptyTitle>
          <EmptyDescription>{error.message}</EmptyDescription>
        </EmptyHeader>
        <Button variant="outline" onClick={() => refetch()}>
          Try again
        </Button>
      </Empty>
    );
  }
  if (!data?.findings.length) {
    return (
      <Empty>
        <EmptyHeader>
          <EmptyTitle>No findings — the wiki is healthy.</EmptyTitle>
        </EmptyHeader>
      </Empty>
    );
  }
  return (
    <div className="flex flex-col gap-4 overflow-auto p-4">
      {Object.entries(groups).map(([category, findings]) => (
        <section key={category} className="flex flex-col gap-2">
          <Heading size="sm">{category.replaceAll("_", " ")}</Heading>
          <div className="flex flex-col gap-1">
            {findings.map((finding, index) => (
              <Button
                key={`${finding.path}-${index}`}
                variant="link-muted"
                className="h-auto justify-start"
                onClick={() => onOpenPage(finding.path)}
              >
                <span className="flex flex-col items-start gap-1 text-left">
                  <Text size="sm" weight="medium">
                    {finding.path}
                  </Text>
                  <Text size="xs" variant="muted">
                    {finding.message}
                  </Text>
                </span>
              </Button>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

export function groupFindings(
  findings: ContextWikiHealthFinding[],
): Record<string, ContextWikiHealthFinding[]> {
  return findings.reduce<Record<string, ContextWikiHealthFinding[]>>(
    (groups, finding) => {
      const group = groups[finding.category] ?? [];
      group.push(finding);
      groups[finding.category] = group;
      return groups;
    },
    {},
  );
}
