import {
  ArrowSquareOutIcon,
  CaretRightIcon,
  FileMdIcon,
  FileTextIcon,
  LinkIcon,
  PencilSimpleIcon,
  PlusIcon,
  XIcon,
} from "@phosphor-icons/react";
import {
  CONTEXT_OBJECT_KIND_LABELS,
  type ContextLink,
  type ContextObject,
  isHttpUrl,
} from "@posthog/core/canvas/contextDocument";
import { parseContextSourceInput } from "@posthog/core/canvas/contextSources";
import { Button, cn, Text } from "@posthog/quill";
import {
  type ContextSources,
  useContextSources,
} from "@posthog/ui/features/canvas/hooks/useContextSources";
import { useWatchedObjectPreview } from "@posthog/ui/features/canvas/hooks/useWatchedObjectPreview";
import { ServerIcon } from "@posthog/ui/features/mcp-servers/components/parts/icons";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { useNavigate } from "@tanstack/react-router";
import { type ReactNode, useMemo, useState } from "react";
import { AddContextDialog } from "./AddContextDialog";
import { connectLabel, unconnectedWarning } from "./addContextRows";
import { KnowledgeBriefing } from "./KnowledgeBriefing";
import { KIND_ICONS } from "./kindIcons";

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
  const [briefing, setBriefing] = useState<Briefing>(
    startWriting ? "edit" : "closed",
  );
  const sources = useContextSources();
  const hasKnowledge = knowledge.trim().length > 0;
  const sections = useMemo(() => sectionHeadings(knowledge), [knowledge]);
  const briefingOpen = briefing !== "closed";

  return (
    <section className="flex flex-col gap-1">
      <div className="flex items-center justify-between gap-2">
        <Text size="xs" weight="medium" variant="muted">
          Business knowledge
        </Text>
        <Button
          variant="link-muted"
          size="xs"
          disabled={isSaving}
          onClick={() => setAdding(true)}
        >
          <PlusIcon size={12} />
          Add context…
        </Button>
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
            onOpen={() =>
              setBriefing(
                briefingOpen ? "closed" : hasKnowledge ? "read" : "edit",
              )
            }
            actions={
              <Button
                variant="default"
                size="icon-xs"
                aria-label="Edit CONTEXT.md"
                title="Edit CONTEXT.md"
                disabled={isSaving}
                onClick={() => setBriefing("edit")}
                className="text-muted-foreground"
              >
                <PencilSimpleIcon size={13} />
              </Button>
            }
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
                key={briefing}
                knowledge={knowledge}
                onSave={onKnowledgeSave}
                onAskAgent={onAskAgent}
                isSaving={isSaving}
                startEditing={briefing === "edit"}
              />
            </div>
          ) : null}
        </li>

        {links.map((link, index) => (
          <li key={`${link.target}-${index}`}>
            <LinkRow
              link={link}
              sources={sources}
              onRemove={() =>
                onLinksChange(links.filter((_, i) => i !== index))
              }
              disabled={isSaving}
            />
          </li>
        ))}

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
        <AddContextDialog
          isSaving={isSaving}
          onAddLink={(link) => onLinksChange([...links, link])}
          onAddObject={(object) => onObjectsChange([...objects, object])}
          onClose={() => setAdding(false)}
        />
      ) : null}
    </section>
  );
}

/**
 * A doc, a file, or a link. A link from a known source shows that source's
 * icon and what it is; when the source's server is not connected, the row
 * offers to connect it, because agents cannot read the link until then.
 */
function LinkRow({
  link,
  sources,
  onRemove,
  disabled,
}: {
  link: ContextLink;
  sources: ContextSources;
  onRemove: () => void;
  disabled: boolean;
}) {
  const navigate = useNavigate();
  const external = isHttpUrl(link.target);
  const parsed = external ? parseContextSourceInput(link.target, null) : null;
  const state = parsed ? sources.byId(parsed.source.id) : undefined;
  const unconnected = state !== undefined && state.status !== "connected";
  const kind = parsed?.item.label ?? null;
  const name = state?.source.name ?? "";
  const warning = state ? unconnectedWarning(state) : null;
  const action = !state
    ? null
    : state.connecting
      ? "Waiting"
      : state.needsCredentials
        ? connectLabel(state)
        : `${connectLabel(state)} ${name}`;
  return (
    <KnowledgeRow
      icon={
        parsed ? (
          <ServerIcon iconDomain={parsed.source.iconDomain} size={15} />
        ) : external ? (
          <LinkIcon size={15} />
        ) : (
          <FileTextIcon size={15} />
        )
      }
      title={link.title}
      meta={
        unconnected && warning ? (
          <span className="text-warning-foreground">{warning}</span>
        ) : (
          [kind, link.note || (external && !kind ? hostOf(link.target) : null)]
            .filter(Boolean)
            .join(" · ") || (external ? null : link.target)
        )
      }
      mono={!external && !link.note}
      onOpen={external ? () => openExternalUrl(link.target) : null}
      onRemove={onRemove}
      actions={
        unconnected && state ? (
          <Button
            variant="outline"
            size="xs"
            disabled={state.connecting}
            onClick={() =>
              state.needsCredentials
                ? void navigate({ to: "/mcp-servers" })
                : sources.connect(state)
            }
          >
            {action}
          </Button>
        ) : null
      }
      trailing={external ? <OpenGlyph /> : null}
      disabled={disabled}
    />
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
    parts.length === 0 ? (
      CONTEXT_OBJECT_KIND_LABELS[object.kind]
    ) : (
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
    );
  return (
    <KnowledgeRow
      icon={KIND_ICONS[object.kind]}
      title={data?.title || object.title}
      meta={meta}
      onOpen={() => openExternalUrl(object.url)}
      onRemove={onRemove}
      trailing={<OpenGlyph />}
      disabled={disabled}
    />
  );
}

/**
 * One row of knowledge: an icon for what it is, the short line under the
 * title, and where it leads. Nothing sits to the right but the controls.
 */
function KnowledgeRow({
  icon,
  title,
  meta,
  mono = false,
  onOpen,
  onRemove,
  actions,
  trailing,
  expanded,
  disabled = false,
}: {
  icon: ReactNode;
  title: string;
  meta: ReactNode;
  mono?: boolean;
  onOpen: (() => void) | null;
  onRemove?: () => void;
  /** Controls that stay visible; the remove button only shows on hover. */
  actions?: ReactNode;
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
        {actions}
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

type Briefing = "closed" | "read" | "edit";

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
