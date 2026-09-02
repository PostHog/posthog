import { ArrowLineDownIcon, SpinnerGapIcon } from "@phosphor-icons/react";
import type { DocSchemas } from "@posthog/api-client/docs";
import { parseObjectTags } from "@posthog/core/inbox/objectTags";
import {
  cn,
  ThreadItem,
  ThreadItemAction,
  ThreadItemActions,
  ThreadItemAuthor,
  ThreadItemBody,
  ThreadItemContent,
  ThreadItemGutter,
  ThreadItemHeader,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { UserAvatar } from "@posthog/ui/features/auth/UserAvatar";
import { MentionText } from "@posthog/ui/features/canvas/components/MentionText";
import { ThreadTimestamp } from "@posthog/ui/features/canvas/components/ThreadTimestamp";
import { useEvidenceUrl } from "@posthog/ui/features/editor/components/EvidenceRefChip";
import { DocMark } from "@posthog/ui/primitives/DocMark";
import { HighlightedCode } from "@posthog/ui/primitives/HighlightedCode";
import { Spin } from "@posthog/ui/primitives/Spinner";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { Fragment, type ReactNode, useMemo } from "react";
import {
  DocRefCardAction,
  DocRefCardActions,
  DocRefHover,
} from "../extensions/inline/DocRefCard";

export function personName(person: DocSchemas.DocPerson | null): string {
  if (!person) return "Someone";
  const full = `${person.first_name} ${person.last_name}`.trim();
  return full || person.email;
}

const EMPHASIS = /(\*\*[^*]+\*\*|`[^`]+`)/g;

/** Bold and code, the two marks an agent uses in a short reply. Nothing else is markdown here. */
function emphasis(text: string, keyBase: string): ReactNode[] {
  let offset = 0;
  return text.split(EMPHASIS).map((part) => {
    const key = `${keyBase}:${offset}`;
    offset += part.length;
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={key}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return (
        <code
          key={key}
          className="rounded-(--radius-1) bg-(--gray-3) px-1 text-[12px]"
        >
          {part.slice(1, -1)}
        </code>
      );
    }
    return part;
  });
}

/**
 * What the agent wrote, with the objects it named as chips. A query it cited
 * shows its label and keeps the SQL for the hover, so the row reads as a
 * sentence and not as a listing. Keys are character offsets: stable for one text.
 */
function AgentText({ content }: { content: string }) {
  const segments = useMemo(() => {
    let offset = 0;
    return parseObjectTags(content).map((segment) => {
      const key = String(offset);
      offset += segment.type === "tag" ? 1 : segment.value.length;
      return { segment, key };
    });
  }, [content]);
  return (
    <>
      {segments.map(({ segment, key }) => {
        if (segment.type !== "tag") {
          return <Fragment key={key}>{emphasis(segment.value, key)}</Fragment>;
        }
        const { ref } = segment;
        if (ref.kind === "hogql") {
          return <SqlChip key={key} query={ref.id} label={ref.label} />;
        }
        return (
          <span key={key} className="doc-post-sql">
            {ref.label || ref.id}
          </span>
        );
      })}
    </>
  );
}

/** A query the agent cited: its label in the row, the SQL in the card. */
function SqlChip({ query, label }: { query: string; label: string }) {
  const url = useEvidenceUrl("hogql", query);
  return (
    <DocRefHover
      card={{
        title: label && label !== "SQL query" ? label : "Query",
        render: (close) => (
          <div className="w-80 p-2.5">
            <div className="max-h-40 overflow-hidden whitespace-pre-wrap break-words font-mono text-[11.5px] leading-[1.5]">
              <HighlightedCode code={query.trim()} language="sql" />
            </div>
            {url ? (
              <DocRefCardActions>
                <DocRefCardAction
                  onSelect={() => {
                    openExternalUrl(url);
                    close();
                  }}
                >
                  Open in PostHog
                </DocRefCardAction>
              </DocRefCardActions>
            ) : null}
          </div>
        ),
      }}
      trigger={
        <span className="doc-post-sql">
          <DocMark variant="agent" size={10} />
          {label && label !== "SQL query" ? label : "query"}
          <code>{query.replace(/\s+/g, " ").trim()}</code>
        </span>
      }
    />
  );
}

function AgentAvatar({ working }: { working?: boolean }) {
  return (
    <span className="doc-agent-avatar">
      <DocMark
        variant="agent"
        state={working ? "working" : "still"}
        size={13}
      />
    </span>
  );
}

/**
 * One post in a doc thread. A person's row wears their face; the agent's wears
 * the mark; a system line has no author and sits quietly between them.
 */
export function DocPostRow({
  post,
  currentUserEmail,
  onAddToPage,
}: {
  post: DocSchemas.DiscussionPost;
  currentUserEmail?: string | null;
  /** Offered on the agent's rows: what it said goes into the page at the caret. */
  onAddToPage?: (text: string) => void;
}) {
  if (post.author_kind === "system") {
    return (
      <div className="flex items-center gap-2 px-3 py-1 text-(--gray-10) text-[12px]">
        <span className="h-px flex-1 bg-(--gray-4)" />
        <span className="shrink-0">{post.content}</span>
        <span className="h-px flex-1 bg-(--gray-4)" />
      </div>
    );
  }

  const agent = post.author_kind === "agent";
  return (
    <ThreadItem>
      <ThreadItemGutter className="justify-center">
        {agent ? (
          <AgentAvatar />
        ) : (
          <UserAvatar
            user={post.created_by}
            size="sm"
            className="sticky top-2"
          />
        )}
      </ThreadItemGutter>
      <ThreadItemContent>
        <ThreadItemHeader>
          <ThreadItemAuthor className="text-[13px]">
            {agent ? "Agent" : personName(post.created_by)}
          </ThreadItemAuthor>
          <ThreadTimestamp dateTime={post.created_at} />
          {post.sent_to_agent ? (
            <span className="text-(--gray-9) text-[11px]">· to the agent</span>
          ) : null}
        </ThreadItemHeader>
        <ThreadItemBody
          className={cn("mt-1 whitespace-pre-wrap break-words text-[13px]")}
        >
          {agent ? (
            <AgentText content={post.content} />
          ) : (
            <MentionText
              content={post.content}
              currentUserEmail={currentUserEmail}
            />
          )}
        </ThreadItemBody>
      </ThreadItemContent>
      {agent && onAddToPage ? (
        <ThreadItemActions>
          <Tooltip>
            <TooltipTrigger
              render={
                <ThreadItemAction
                  label="Add to page"
                  onClick={() => onAddToPage(post.content)}
                >
                  <ArrowLineDownIcon size={14} />
                </ThreadItemAction>
              }
            />
            <TooltipContent>Add to page</TooltipContent>
          </Tooltip>
        </ThreadItemActions>
      ) : null}
    </ThreadItem>
  );
}

/** The turn the agent is writing now, in the window that can see it stream. */
export function DocStreamingRow({ text }: { text: string | null }) {
  return (
    <ThreadItem>
      <ThreadItemGutter className="justify-center">
        <AgentAvatar working />
      </ThreadItemGutter>
      <ThreadItemContent>
        <ThreadItemHeader>
          <ThreadItemAuthor className="text-[13px]">Agent</ThreadItemAuthor>
          <span className="flex items-center gap-1 text-(--gray-9) text-[11px]">
            <Spin>
              <SpinnerGapIcon size={11} />
            </Spin>
            writing
          </span>
        </ThreadItemHeader>
        {text ? (
          <ThreadItemBody className="mt-1 whitespace-pre-wrap break-words text-(--gray-11) text-[13px]">
            <AgentText content={text} />
          </ThreadItemBody>
        ) : null}
      </ThreadItemContent>
    </ThreadItem>
  );
}
