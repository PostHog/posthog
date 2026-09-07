import {
  ChartLineIcon,
  FileTextIcon,
  FlagIcon,
  FlaskIcon,
  FolderIcon,
  TerminalIcon,
  WarningIcon,
} from "@phosphor-icons/react";
import type { MentionChip } from "@posthog/core/message-editor/content";
import { xmlToContent } from "@posthog/core/message-editor/content";
import { Chip } from "@posthog/quill";
import { splitMentionSegments } from "@posthog/shared";
import { splitLinkSegments } from "@posthog/ui/features/canvas/utils/linkify";
import { GithubRefChip } from "@posthog/ui/features/editor/components/GithubRefChip";
import { parseGithubIssueUrl } from "@posthog/ui/features/message-editor/githubIssueUrl";
import { handleShareLinkClick } from "@posthog/ui/utils/shareLinks";
import { Fragment, useMemo } from "react";
import "./mention-chip.css";

type RenderSegment =
  | { type: "text"; text: string }
  | { type: "link"; text: string; href: string }
  | { type: "agent"; text: string }
  | { type: "mention"; name: string; email: string }
  | { type: "chip"; chip: MentionChip };

const chipIcons = {
  file: FileTextIcon,
  folder: FolderIcon,
  command: TerminalIcon,
  error: WarningIcon,
  experiment: FlaskIcon,
  insight: ChartLineIcon,
  feature_flag: FlagIcon,
} as const;

function StructuredChip({ chip }: { chip: MentionChip }) {
  if (chip.type === "github_issue" || chip.type === "github_pr") {
    const githubRef = parseGithubIssueUrl(chip.id);
    if (githubRef) {
      return (
        <GithubRefChip href={githubRef.normalizedUrl} kind={githubRef.kind}>
          {chip.label}
        </GithubRefChip>
      );
    }
  }

  const Icon = chipIcons[chip.type as keyof typeof chipIcons];
  if (!Icon) return <>@{chip.label}</>;
  return (
    <Chip
      size="xs"
      className="mx-0.5 inline-flex max-w-full whitespace-nowrap align-middle"
    >
      <Icon size={10} />
      <span className="min-w-0 truncate">
        {chip.type === "command" ? "/" : "@"}
        {chip.label}
      </span>
    </Chip>
  );
}

// The plain (not-the-viewer) mention chip look, also used by surfaces that
// render a mention-styled name without real mention semantics (e.g. the
// channel feed's "started a new task" row).
export const mentionChipClass = "mention-chip";

/**
 * Thread message content with inline mention tokens rendered as highlighted
 * `@Name` chips (a mention of the viewer gets the stronger treatment) and
 * bare URLs rendered as links.
 */
export function MentionText({
  content,
  currentUserEmail,
  className,
}: {
  content: string;
  currentUserEmail?: string | null;
  className?: string;
}) {
  // Key each segment by its character offset — stable for a given content.
  const segments = useMemo(() => {
    let offset = 0;
    const entries: Array<{ segment: RenderSegment; key: string }> = [];
    const push = (segment: RenderSegment, length: number) => {
      entries.push({ segment, key: `${offset}` });
      offset += length;
    };
    const pushAgentMentions = (text: string) => {
      let cursor = 0;
      for (const match of text.matchAll(/(^|\s)(@agent)\b/gi)) {
        const mentionStart = (match.index ?? 0) + match[1].length;
        if (mentionStart > cursor) {
          push(
            { type: "text", text: text.slice(cursor, mentionStart) },
            mentionStart - cursor,
          );
        }
        push({ type: "agent", text: match[2] }, match[2].length);
        cursor = mentionStart + match[2].length;
      }
      if (cursor < text.length) {
        push({ type: "text", text: text.slice(cursor) }, text.length - cursor);
      }
    };
    const pushMentions = (text: string) => {
      for (const segment of splitMentionSegments(text)) {
        if (segment.type === "mention") {
          push(
            { type: "mention", name: segment.name, email: segment.email },
            segment.text.length,
          );
        } else {
          pushAgentMentions(segment.text);
        }
      }
    };
    for (const contentSegment of xmlToContent(content).segments) {
      if (contentSegment.type === "chip") {
        push({ type: "chip", chip: contentSegment.chip }, 1);
        continue;
      }
      for (const segment of splitLinkSegments(contentSegment.text)) {
        if (segment.type === "link") {
          push(segment, segment.text.length);
        } else {
          pushMentions(segment.text);
        }
      }
    }
    return entries;
  }, [content]);
  const selfEmail = currentUserEmail?.toLowerCase();
  return (
    <span className={className}>
      {segments.map(({ segment, key }) => {
        if (segment.type === "chip") {
          return <StructuredChip key={key} chip={segment.chip} />;
        }
        if (segment.type === "agent") {
          return (
            <span key={key} className={mentionChipClass}>
              {segment.text}
            </span>
          );
        }
        if (segment.type === "mention") {
          return (
            <span
              key={key}
              className={
                selfEmail && segment.email.toLowerCase() === selfEmail
                  ? `${mentionChipClass} mention-chip--self`
                  : mentionChipClass
              }
              title={segment.email}
            >
              @{segment.name}
            </span>
          );
        }
        if (segment.type === "link") {
          return (
            <a
              key={key}
              href={segment.href}
              onClick={(event) => handleShareLinkClick(segment.href, event)}
              target="_blank"
              rel="noopener noreferrer"
              className="text-[var(--accent-11)] underline underline-offset-2 hover:text-[var(--accent-12)]"
            >
              {segment.text}
            </a>
          );
        }
        return <Fragment key={key}>{segment.text}</Fragment>;
      })}
    </span>
  );
}
