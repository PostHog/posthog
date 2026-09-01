import { XIcon } from "@phosphor-icons/react";
import type { DocSchemas } from "@posthog/api-client/docs";
import {
  Button,
  cn,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
  Separator,
  Spinner,
  Text,
  Textarea,
} from "@posthog/quill";
import { useState } from "react";

function personName(person: DocSchemas.DocPerson | null): string {
  if (!person) return "Someone";
  const full = `${person.first_name} ${person.last_name}`.trim();
  return full || person.email;
}

/**
 * The discussions on the open doc.
 *
 * A thread is anchored to a phrase. Clicking one highlights that phrase in the
 * text; clicking the phrase opens the thread here.
 */
export function DiscussionsPanel({
  threads,
  isLoading,
  selectedAnchorKey,
  pendingAnchor,
  onSelect,
  onReply,
  onStartThread,
  onCancelPending,
  onResolveChange,
  onClose,
}: {
  threads: DocSchemas.DiscussionThread[];
  isLoading: boolean;
  selectedAnchorKey: string | null;
  /** A phrase that is marked in the text but has no thread yet. */
  pendingAnchor: { anchorKey: string; anchorText: string } | null;
  onSelect: (anchorKey: string) => void;
  onReply: (threadId: string, content: string) => Promise<unknown>;
  onStartThread: (content: string) => Promise<unknown>;
  onCancelPending: () => void;
  onResolveChange: (threadId: string, resolved: boolean) => void;
  onClose: () => void;
}) {
  return (
    <aside className="flex w-80 shrink-0 flex-col border-(--gray-5) border-l">
      <div className="flex items-center justify-between px-3 py-2">
        <Text weight="medium">Discussions</Text>
        <Button
          size="sm"
          variant="default"
          aria-label="Close discussions"
          onClick={onClose}
        >
          <XIcon size={14} />
        </Button>
      </div>
      <Separator />

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {pendingAnchor ? (
          <NewThreadCard
            anchorText={pendingAnchor.anchorText}
            onSubmit={onStartThread}
            onCancel={onCancelPending}
          />
        ) : null}
        {isLoading ? (
          <div className="flex justify-center py-8">
            <Spinner />
          </div>
        ) : threads.length === 0 ? (
          <Empty>
            <EmptyHeader>
              <EmptyTitle>No discussions yet</EmptyTitle>
              <EmptyDescription>
                Select a phrase in the doc and choose Discuss to start one.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <ul className="flex flex-col gap-3">
            {threads.map((thread) => (
              <ThreadCard
                key={thread.id}
                thread={thread}
                selected={thread.anchor_key === selectedAnchorKey}
                onSelect={() => onSelect(thread.anchor_key)}
                onReply={(content) => onReply(thread.id, content)}
                onResolveChange={(resolved) =>
                  onResolveChange(thread.id, resolved)
                }
              />
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
}

function NewThreadCard({
  anchorText,
  onSubmit,
  onCancel,
}: {
  anchorText: string;
  onSubmit: (content: string) => Promise<unknown>;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);

  const send = async () => {
    const content = draft.trim();
    if (!content || sending) return;
    setSending(true);
    try {
      await onSubmit(content);
      setDraft("");
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="mb-3 rounded-(--radius-3) border border-(--amber-8) p-2">
      <Text size="sm" className="mb-1 truncate text-(--gray-11) italic">
        “{anchorText || "a phrase in the doc"}”
      </Text>
      <Textarea
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        placeholder="What do you want to ask about this?"
        rows={3}
        className="text-sm"
        autoFocus
      />
      <div className="mt-1 flex items-center justify-end gap-2">
        <Button size="sm" variant="default" onClick={onCancel}>
          Cancel
        </Button>
        <Button
          size="sm"
          variant="primary"
          disabled={sending || draft.trim().length === 0}
          onClick={() => void send()}
        >
          {sending ? "Starting…" : "Start"}
        </Button>
      </div>
    </div>
  );
}

function ThreadCard({
  thread,
  selected,
  onSelect,
  onReply,
  onResolveChange,
}: {
  thread: DocSchemas.DiscussionThread;
  selected: boolean;
  onSelect: () => void;
  onReply: (content: string) => Promise<unknown>;
  onResolveChange: (resolved: boolean) => void;
}) {
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);

  const send = async () => {
    const content = draft.trim();
    if (!content || sending) return;
    setSending(true);
    try {
      await onReply(content);
      setDraft("");
    } finally {
      setSending(false);
    }
  };

  return (
    <li>
      <div
        className={cn(
          "rounded-(--radius-3) border p-2",
          selected ? "border-(--amber-8)" : "border-(--gray-6)",
          thread.resolved && "opacity-70",
        )}
      >
        <button
          type="button"
          className="mb-1 w-full truncate text-left text-(--gray-11) text-xs italic"
          onClick={onSelect}
        >
          “{thread.anchor_text || "a phrase in the doc"}”
        </button>

        <Post
          name={personName(thread.created_by)}
          content={thread.content}
          at={thread.created_at}
        />
        {thread.replies.map((reply) => (
          <Post
            key={reply.id}
            name={personName(reply.created_by)}
            content={reply.content}
            at={reply.created_at}
          />
        ))}

        <Textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Reply"
          rows={2}
          className="mt-2 text-sm"
        />
        <div className="mt-1 flex items-center justify-between gap-2">
          <Button
            size="sm"
            variant="default"
            onClick={() => onResolveChange(!thread.resolved)}
          >
            {thread.resolved ? "Reopen" : "Mark handled"}
          </Button>
          <Button
            size="sm"
            variant="primary"
            disabled={sending || draft.trim().length === 0}
            onClick={() => void send()}
          >
            {sending ? "Sending…" : "Reply"}
          </Button>
        </div>
      </div>
    </li>
  );
}

function Post({
  name,
  content,
  at,
}: {
  name: string;
  content: string;
  at: string;
}) {
  return (
    <div className="mt-1.5">
      <Text size="sm" weight="medium">
        {name}
        <span className="ml-1 font-normal text-(--gray-11) text-xs">
          {new Date(at).toLocaleString()}
        </span>
      </Text>
      <Text size="sm" className="whitespace-pre-wrap">
        {content}
      </Text>
    </div>
  );
}
