import {
  ArrowSquareOutIcon,
  BugIcon,
  CaretRightIcon,
  ChartBarIcon,
  ChatsCircleIcon,
  CursorClickIcon,
  FileMdIcon,
  FileTextIcon,
  FlagIcon,
  FlaskIcon,
  LightningIcon,
  LinkIcon,
  NotebookIcon,
  PlayCircleIcon,
  PlusIcon,
  SquaresFourIcon,
  UserIcon,
  UsersThreeIcon,
  XIcon,
} from "@phosphor-icons/react";
import {
  CONTEXT_OBJECT_KIND_LABELS,
  type ContextLink,
  type ContextObject,
  type ContextObjectKind,
  isHttpUrl,
  parsePostHogObjectUrl,
} from "@posthog/core/canvas/contextDocument";
import { Button, cn, Input, Text } from "@posthog/quill";
import { useWatchedObjectPreview } from "@posthog/ui/features/canvas/hooks/useWatchedObjectPreview";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { type ReactNode, useMemo, useState } from "react";
import { KnowledgeBriefing } from "./KnowledgeBriefing";

interface KnowledgeListProps {
  knowledge: string;
  links: ContextLink[];
  objects: ContextObject[];
  onKnowledgeSave: (knowledge: string) => Promise<void>;
  onLinksChange: (links: ContextLink[]) => Promise<void>;
  onObjectsChange: (objects: ContextObject[]) => Promise<void>;
  onAskAgent: () => void;
  isSaving: boolean;
  /** Open the briefing straight into the editor, seeded with the template. */
  startWriting?: boolean;
}

/**
 * Everything a person told this space, as one flat list: the briefing first,
 * then the docs and files, then the objects the space owns. Nothing here is
 * inferred; what agents find about these rows shows up under Signals.
 */
export function KnowledgeList({
  knowledge,
  links,
  objects,
  onKnowledgeSave,
  onLinksChange,
  onObjectsChange,
  onAskAgent,
  isSaving,
  startWriting = false,
}: KnowledgeListProps) {
  const [adding, setAdding] = useState(false);
  const [briefingOpen, setBriefingOpen] = useState(startWriting);
  const hasKnowledge = knowledge.trim().length > 0;
  const sections = useMemo(() => sectionHeadings(knowledge), [knowledge]);

  return (
    <section className="flex flex-col gap-1">
      <div className="flex items-center justify-between gap-2">
        <Text size="xs" weight="medium" variant="muted">
          Business knowledge
        </Text>
        {adding ? null : (
          <Button
            variant="link-muted"
            size="xs"
            disabled={isSaving}
            onClick={() => setAdding(true)}
          >
            <PlusIcon size={12} />
            Add doc or link
          </Button>
        )}
      </div>

      <ul className="flex flex-col divide-y divide-border border-border border-y">
        <li>
          <KnowledgeRow
            icon={<FileMdIcon size={15} />}
            title="CONTEXT.md"
            meta={
              sections.length > 0
                ? sections.join(" · ")
                : hasKnowledge
                  ? firstLine(knowledge)
                  : "Nothing written yet. What this is, how to work here, key files, gotchas."
            }
            kind={
              sections.length > 0
                ? `${sections.length} ${sections.length === 1 ? "section" : "sections"}`
                : hasKnowledge
                  ? "Briefing"
                  : "Empty"
            }
            onOpen={() => setBriefingOpen((open) => !open)}
            trailing={
              <CaretRightIcon
                size={13}
                className={cn(
                  "transition-transform",
                  briefingOpen && "rotate-90",
                )}
              />
            }
            expanded={briefingOpen}
          />
          {briefingOpen ? (
            <div className="pt-1 pb-5 @lg:pl-[30px]">
              <KnowledgeBriefing
                knowledge={knowledge}
                onSave={onKnowledgeSave}
                onAskAgent={onAskAgent}
                isSaving={isSaving}
                startEditing={startWriting || !hasKnowledge}
              />
            </div>
          ) : null}
        </li>

        {links.map((link, index) => {
          const external = isHttpUrl(link.target);
          return (
            <li key={`${link.target}-${index}`}>
              <KnowledgeRow
                icon={
                  external ? <LinkIcon size={15} /> : <FileTextIcon size={15} />
                }
                title={link.title}
                meta={link.note || (external ? null : link.target)}
                mono={!external && !link.note}
                kind={external ? hostOf(link.target) : "File"}
                onOpen={external ? () => openExternalUrl(link.target) : null}
                onRemove={() =>
                  onLinksChange(links.filter((_, i) => i !== index))
                }
                trailing={external ? <OpenGlyph /> : null}
                disabled={isSaving}
              />
            </li>
          );
        })}

        {objects.map((object, index) => (
          <li key={`${object.url}-${index}`}>
            <ObjectRow
              object={object}
              onRemove={() =>
                onObjectsChange(objects.filter((_, i) => i !== index))
              }
              disabled={isSaving}
            />
          </li>
        ))}
      </ul>

      {adding ? (
        <div className="pt-3">
          <AddKnowledgeForm
            isSaving={isSaving}
            onAddLink={async (link) => {
              await onLinksChange([...links, link]);
              setAdding(false);
            }}
            onAddObject={async (object) => {
              await onObjectsChange([...objects, object]);
              setAdding(false);
            }}
            onCancel={() => setAdding(false)}
          />
        </div>
      ) : null}
    </section>
  );
}

const TONE_DOT: Record<string, string> = {
  positive: "bg-success-foreground",
  neutral: "bg-muted-foreground/50",
  caution: "bg-warning-foreground",
  critical: "bg-destructive",
};

/** A linked object. Its short description is its live state, not a hand-written note. */
function ObjectRow({
  object,
  onRemove,
  disabled,
}: {
  object: ContextObject;
  onRemove: () => void;
  disabled: boolean;
}) {
  const preview = useWatchedObjectPreview(object);
  const data = preview.data ?? null;
  const facts = data?.facts?.slice(0, 2) ?? [];
  const parts = [...(data?.status ? [data.status.label] : []), ...facts];
  const meta =
    parts.length > 0 ? (
      <span className="flex items-center gap-1.5">
        {data?.status ? (
          <span
            className={cn(
              "size-1.5 shrink-0 rounded-full",
              TONE_DOT[data.status.tone] ?? TONE_DOT.neutral,
            )}
          />
        ) : null}
        {parts.map((part, index) => (
          <span key={part} className="flex items-center gap-1.5">
            {index > 0 ? <span aria-hidden="true">·</span> : null}
            <span>{part}</span>
          </span>
        ))}
      </span>
    ) : null;
  return (
    <KnowledgeRow
      icon={KIND_ICONS[object.kind]}
      title={data?.title || object.title}
      meta={meta}
      kind={CONTEXT_OBJECT_KIND_LABELS[object.kind]}
      onOpen={() => openExternalUrl(object.url)}
      onRemove={onRemove}
      trailing={<OpenGlyph />}
      disabled={disabled}
    />
  );
}

/**
 * One row of knowledge: what it is, the short line under it, and where it
 * leads. The kind sits at the right so the eye can scan it as a column.
 */
function KnowledgeRow({
  icon,
  title,
  meta,
  kind,
  mono = false,
  onOpen,
  onRemove,
  trailing,
  expanded,
  disabled = false,
}: {
  icon: ReactNode;
  title: string;
  meta: ReactNode;
  kind: string;
  mono?: boolean;
  onOpen: (() => void) | null;
  onRemove?: () => void;
  trailing: ReactNode;
  /** Set on the one row that opens in place; the others lead somewhere. */
  expanded?: boolean;
  disabled?: boolean;
}) {
  const body = (
    <>
      <span className="flex size-[18px] shrink-0 items-center justify-center text-muted-foreground">
        {icon}
      </span>
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="truncate font-medium text-foreground text-xs">
          {title}
        </span>
        {meta ? (
          <span
            className={cn(
              "truncate text-muted-foreground text-xxs",
              mono && "font-mono",
            )}
          >
            {meta}
          </span>
        ) : null}
      </span>
    </>
  );
  return (
    <div
      className={cn(
        "group/row -mx-3 flex w-[calc(100%+1.5rem)] items-center gap-3 rounded-md px-3 py-2.5 transition-colors hover:bg-fill-hover",
        expanded === true && "bg-fill-hover",
      )}
    >
      {onOpen ? (
        <button
          type="button"
          onClick={onOpen}
          className="flex min-w-0 flex-1 items-center gap-3 text-left"
          aria-expanded={expanded}
        >
          {body}
        </button>
      ) : (
        <span className="flex min-w-0 flex-1 items-center gap-3">{body}</span>
      )}
      <span className="flex shrink-0 items-center gap-1">
        <span className="w-24 truncate text-right text-muted-foreground text-xxs @lg:w-28">
          {kind}
        </span>
        {onRemove ? (
          <Button
            variant="default"
            size="icon-xs"
            aria-label={`Remove ${title}`}
            disabled={disabled}
            onClick={() => void onRemove()}
            className="opacity-0 transition-opacity focus-visible:opacity-100 group-focus-within/row:opacity-100 group-hover/row:opacity-100"
          >
            <XIcon size={13} />
          </Button>
        ) : null}
        <span className="flex size-6 shrink-0 items-center justify-center text-muted-foreground">
          {trailing}
        </span>
      </span>
    </div>
  );
}

/** The arrow only shows when the pointer is on the row; the row is the link. */
function OpenGlyph() {
  return (
    <ArrowSquareOutIcon
      size={13}
      className="opacity-0 transition-opacity group-focus-within/row:opacity-100 group-hover/row:opacity-100"
    />
  );
}

type Detected = "object" | "link" | "file";

/**
 * One box for everything: a PostHog URL becomes a live object, any other URL
 * a link, and anything else a repository path. The second line is the short
 * description a reader sees under the row.
 */
function AddKnowledgeForm({
  onAddLink,
  onAddObject,
  onCancel,
  isSaving,
}: {
  onAddLink: (link: ContextLink) => Promise<void>;
  onAddObject: (object: ContextObject) => Promise<void>;
  onCancel: () => void;
  isSaving: boolean;
}) {
  const [target, setTarget] = useState("");
  const [note, setNote] = useState("");
  const trimmed = target.trim();
  const parsed = useMemo(() => parsePostHogObjectUrl(trimmed), [trimmed]);
  const detected: Detected | null = !trimmed
    ? null
    : parsed
      ? "object"
      : isHttpUrl(trimmed)
        ? "link"
        : "file";
  const detectedLabel =
    detected === "object" && parsed
      ? CONTEXT_OBJECT_KIND_LABELS[parsed.kind]
      : detected === "link"
        ? "Link"
        : detected === "file"
          ? "Repository file"
          : null;
  const canAdd = detected !== null && !isSaving;

  const submit = async () => {
    if (!canAdd) return;
    if (parsed) {
      await onAddObject({
        kind: parsed.kind,
        url: trimmed,
        title:
          note.trim() ||
          `${CONTEXT_OBJECT_KIND_LABELS[parsed.kind]} ${parsed.id}`,
      });
      return;
    }
    await onAddLink({
      target: trimmed,
      title: titleFromTarget(trimmed),
      note: note.trim(),
    });
  };

  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
      onKeyDown={(e) => {
        if (e.key === "Escape") onCancel();
      }}
    >
      <div className="flex items-center gap-2">
        <span className="flex size-[18px] shrink-0 items-center justify-center text-muted-foreground">
          {detected === "object" && parsed ? (
            KIND_ICONS[parsed.kind]
          ) : detected === "file" ? (
            <FileTextIcon size={15} />
          ) : (
            <LinkIcon size={15} />
          )}
        </span>
        <Input
          value={target}
          onChange={(e) => setTarget(e.target.value)}
          placeholder="Paste a PostHog URL, a link, or a repository path"
          aria-label="PostHog URL, link, or repository path"
          autoFocus
          className="min-w-0 flex-1 font-mono text-xs"
        />
        {detectedLabel ? (
          <Text size="xxs" variant="muted" className="shrink-0">
            {detectedLabel}
          </Text>
        ) : null}
        <Button type="submit" variant="primary" size="xs" disabled={!canAdd}>
          Add
        </Button>
      </div>
      <div className="flex items-center gap-2 pl-[26px]">
        <Input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder={
            parsed ? "Name (optional)" : "What it is, in a few words (optional)"
          }
          aria-label={parsed ? "Name" : "Short description"}
          className="min-w-0 flex-1"
        />
        <Button
          type="button"
          variant="link-muted"
          size="xs"
          onClick={onCancel}
          disabled={isSaving}
        >
          Cancel
        </Button>
      </div>
    </form>
  );
}

const KIND_ICONS: Record<ContextObjectKind, ReactNode> = {
  insight: <ChartBarIcon size={15} />,
  dashboard: <SquaresFourIcon size={15} />,
  flag: <FlagIcon size={15} />,
  experiment: <FlaskIcon size={15} />,
  survey: <ChatsCircleIcon size={15} />,
  error: <BugIcon size={15} />,
  replay: <PlayCircleIcon size={15} />,
  notebook: <NotebookIcon size={15} />,
  cohort: <UsersThreeIcon size={15} />,
  action: <CursorClickIcon size={15} />,
  person: <UserIcon size={15} />,
  event: <LightningIcon size={15} />,
  link: <LinkIcon size={15} />,
};

function sectionHeadings(markdown: string): string[] {
  return [...markdown.matchAll(/^##\s+(.+?)\s*$/gm)].map((m) => m[1]);
}

function firstLine(markdown: string): string {
  const line = markdown
    .split("\n")
    .map((l) => l.trim())
    .find((l) => l.length > 0 && !l.startsWith("#"));
  return line ?? "";
}

function hostOf(url: string): string {
  try {
    return new URL(url).host.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function titleFromTarget(target: string): string {
  if (!isHttpUrl(target)) return target;
  try {
    const url = new URL(target);
    const last = url.pathname.split("/").filter(Boolean).pop();
    return last ? decodeURIComponent(last).replace(/[-_]+/g, " ") : url.host;
  } catch {
    return target;
  }
}
