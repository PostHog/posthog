import { humanizeReportTitle } from "@posthog/core/inbox/reportPresentation";
import { prettifyScoutSkillName } from "@posthog/core/scouts/scoutPresentation";
import type { SignalReport } from "@posthog/shared/types";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import {
  type InboxTriageOrigin,
  useInboxTriageOrigin,
} from "@posthog/ui/features/inbox/hooks/useInboxBackTarget";
import {
  BreadcrumbSegment,
  BreadcrumbSeparator,
} from "@posthog/ui/primitives/Breadcrumb";
import {
  type NavigationSource,
  resolveNavigationSource,
  useReportSourceHref,
} from "@posthog/ui/router/reportNavigation";
import { Link } from "@tanstack/react-router";
import type { ReactElement } from "react";

interface Crumb {
  label: string;
  render?: ReactElement;
}

/** Where a report sits: the list that opened it, its space, then its title. */
export function ReportBreadcrumbs({
  report,
}: {
  report: SignalReport;
}): ReactElement {
  const triageOrigin = useInboxTriageOrigin();
  const sourceHref = useReportSourceHref();
  const { channels } = useChannels();
  const spaceName = (id: string) => channels.find((c) => c.id === id)?.name;
  const crumbs = reportCrumbs(
    resolveNavigationSource(sourceHref),
    report,
    triageOrigin,
    spaceName,
  );

  return (
    <div className="flex min-w-0 items-center gap-0.5 overflow-hidden">
      {crumbs.map((crumb, index) => (
        <div
          key={`${index}-${crumb.label}`}
          className={
            index === crumbs.length - 1
              ? "flex min-w-0 items-center gap-0.5"
              : "flex shrink-0 items-center gap-0.5"
          }
        >
          {index > 0 && <BreadcrumbSeparator />}
          <BreadcrumbSegment
            label={crumb.label}
            strong={index === 0}
            muted={index === crumbs.length - 1}
            shrink={index === crumbs.length - 1}
            render={crumb.render}
          />
        </div>
      ))}
    </div>
  );
}

function reportCrumbs(
  source: NavigationSource | null,
  report: SignalReport,
  triageOrigin: InboxTriageOrigin | null,
  spaceName: (id: string) => string | undefined,
): Crumb[] {
  const crumbs: Crumb[] = [];
  // TanStack blanks history state on a plain Link, so the Reports-list crumb
  // must carry the triage origin forward or triage focus mode dies on the way
  // back.
  const exact = source ? (
    <Link
      to={source.href}
      state={
        source.path === "/inbox/reports" && triageOrigin
          ? (previous) => ({ ...previous, inboxTriageOrigin: triageOrigin })
          : undefined
      }
    />
  ) : undefined;

  if (source?.settingsCategory) {
    crumbs.push({
      label: source.label,
      render: source.agentSkillName ? (
        <Link
          to="/settings/$category"
          params={{ category: source.settingsCategory }}
        />
      ) : (
        exact
      ),
    });
    if (source.agentSkillName) {
      crumbs.push({
        label: prettifyScoutSkillName(source.agentSkillName),
        render: exact,
      });
    }
  } else if (source?.spaceId) {
    const name = spaceName(source.spaceId);
    crumbs.push({ label: name ? `#${name}` : source.label, render: exact });
  } else if (source) {
    crumbs.push({ label: source.label, render: exact });
  } else {
    crumbs.push({
      label: "Self-driving",
      render: (
        <Link
          to="/inbox/reports"
          state={
            triageOrigin
              ? (previous) => ({ ...previous, inboxTriageOrigin: triageOrigin })
              : undefined
          }
        />
      ),
    });
  }

  const ownSpace =
    report.channel_id && report.channel_id !== source?.spaceId
      ? report.channel_id
      : null;
  const ownSpaceName = ownSpace ? spaceName(ownSpace) : undefined;
  if (ownSpace && ownSpaceName) {
    crumbs.push({
      label: `#${ownSpaceName}`,
      render: <Link to="/spaces/$channelId" params={{ channelId: ownSpace }} />,
    });
  }

  crumbs.push({
    label: humanizeReportTitle(report.title, "Untitled report"),
  });
  return crumbs;
}
