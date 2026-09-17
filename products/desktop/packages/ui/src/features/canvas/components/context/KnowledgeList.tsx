import {
  ArrowSquareOutIcon,
  CaretRightIcon,
  FileMdIcon,
  FileTextIcon,
  LinkIcon,
  PlusIcon,
  UploadSimpleIcon,
  XIcon,
} from "@phosphor-icons/react";
import {
  CONTEXT_OBJECT_KIND_LABELS,
  type ContextLink,
  type ContextObject,
  isHttpUrl,
} from "@posthog/core/canvas/contextDocument";
import {
  fileDisplayName,
  isSpaceFile,
} from "@posthog/core/canvas/contextFiles";
import { parseContextSourceInput } from "@posthog/core/canvas/contextSources";
import {
  Button,
  cn,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@posthog/quill";
import {
  type ContextSources,
  useContextSources,
} from "@posthog/ui/features/canvas/hooks/useContextSources";
import { useWatchedObjectPreview } from "@posthog/ui/features/canvas/hooks/useWatchedObjectPreview";
import { useContextWikiPageMutation } from "@posthog/ui/features/context-wiki/hooks/useContextWiki";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { useNavigate } from "@tanstack/react-router";
import { type ReactNode, useState } from "react";
import { AddContextDialog, type AddContextMode } from "./AddContextDialog";
import { EditableNote } from "./EditableNote";
import { KIND_ICONS } from "./kindIcons";
import { SectionHeader } from "./SectionHeader";
import { SourceLogo } from "./SourceLogo";
import { SpaceFileDialog } from "./SpaceFileDialog";
import { connectLabel, unconnectedWarning } from "./sourceStatus";

interface KnowledgeListProps {
  channelName: string;
  links: ContextLink[];
  objects: ContextObject[];
  /** Where this space's extra Markdown files live; null without the context wiki. */
  filesFolder: string | null;
  onOpenContextFile: () => void;
  onLinksChange: (links: ContextLink[]) => Promise<void>;
  onObjectsChange: (objects: ContextObject[]) => Promise<void>;
  isSaving: boolean;
}

/**
 * Everything a person told this space, as one flat list: CONTEXT.md first,
 * then its other Markdown files, links and objects. Markdown opens in an
 * editor; everything else opens where it lives. Nothing here is inferred;
 * what agents find about these rows shows up under Signals.
 */
export function KnowledgeList({
  channelName,
  links,
  objects,
  filesFolder,
  onOpenContextFile,
  onLinksChange,
  onObjectsChange,
  isSaving,
}: KnowledgeListProps) {
  const [adding, setAdding] = useState<AddContextMode | null>(null);
  const [openFile, setOpenFile] = useState<string | null>(null);
  const sources = useContextSources();
  const { mutateAsync: writePage } = useContextWikiPageMutation();

  // CONTEXT.md is saved first so its head moves before the file is written;
  // the file is new, so it has no head to check and is created on the way in.
  const addFile = async (path: string, content: string | null) => {
    await onLinksChange([
      ...links,
      { title: fileDisplayName(path), target: path, note: "" },
    ]);
    if (content !== null) {
      await writePage({ path, content });
    } else {
      setOpenFile(path);
    }
  };

  return (
    <section className="flex flex-col gap-2">
      <SectionHeader
        label="Business knowledge"
        action={
          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <Button variant="link-muted" size="xs" disabled={isSaving}>
                  <PlusIcon size={12} />
                  Add context
                </Button>
              }
            />
            <DropdownMenuContent
              align="end"
              sideOffset={4}
              className="min-w-56"
            >
              <DropdownMenuItem onClick={() => setAdding("link")}>
                <LinkIcon size={14} />
                Link…
              </DropdownMenuItem>
              <DropdownMenuItem
                disabled={!filesFolder}
                onClick={() => setAdding("markdown")}
              >
                <FileMdIcon size={14} />
                Markdown file…
              </DropdownMenuItem>
              <DropdownMenuItem
                disabled={!filesFolder}
                onClick={() => setAdding("upload")}
              >
                <UploadSimpleIcon size={14} />
                Upload a file…
              </DropdownMenuItem>
              {!filesFolder ? (
                <DropdownMenuLabel>
                  Files need the context wiki
                </DropdownMenuLabel>
              ) : null}
            </DropdownMenuContent>
          </DropdownMenu>
        }
      />

      <ul className="flex flex-col divide-y divide-border border-border border-y">
        <li>
          <KnowledgeRow
            icon={<FileMdIcon size={15} />}
            title="CONTEXT.md"
            meta="The root context of this space. Every agent reads it first."
            onOpen={onOpenContextFile}
            trailing={<CaretRightIcon size={13} />}
          />
        </li>

        {links.map((link, index) => (
          <li key={`${link.target}-${index}`}>
            {isSpaceFile(link, filesFolder) ? (
              <KnowledgeRow
                icon={<FileMdIcon size={15} />}
                title={fileDisplayName(link.target)}
                prefix="Markdown file"
                note={link.note}
                onNoteChange={(note) =>
                  onLinksChange(
                    links.map((l, i) => (i === index ? { ...l, note } : l)),
                  )
                }
                onOpen={() => setOpenFile(link.target)}
                onRemove={() =>
                  onLinksChange(links.filter((_, i) => i !== index))
                }
                trailing={<CaretRightIcon size={13} />}
                disabled={isSaving}
              />
            ) : (
              <LinkRow
                link={link}
                sources={sources}
                onChange={(next) =>
                  onLinksChange(links.map((l, i) => (i === index ? next : l)))
                }
                onRemove={() =>
                  onLinksChange(links.filter((_, i) => i !== index))
                }
                disabled={isSaving}
              />
            )}
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
          mode={adding}
          sources={sources}
          filesFolder={filesFolder}
          existingTargets={links.map((link) => link.target)}
          onAddLink={(link) => onLinksChange([...links, link])}
          onAddObject={(object) => onObjectsChange([...objects, object])}
          onAddFile={addFile}
          onClose={() => setAdding(null)}
        />
      ) : null}

      {openFile ? (
        <SpaceFileDialog
          path={openFile}
          channelName={channelName}
          onClose={() => setOpenFile(null)}
        />
      ) : null}
    </section>
  );
}

/**
 * A link. One from a known source shows that source's icon and what it is;
 * when the source's server is not connected, the row offers to connect it,
 * because agents cannot read the link until then. Anything else is a plain
 * link to its host.
 */
function LinkRow({
  link,
  sources,
  onChange,
  onRemove,
  disabled,
}: {
  link: ContextLink;
  sources: ContextSources;
  onChange: (link: ContextLink) => Promise<void>;
  onRemove: () => void;
  disabled: boolean;
}) {
  const navigate = useNavigate();
  const external = isHttpUrl(link.target);
  const parsed = external ? parseContextSourceInput(link.target, null) : null;
  const state = parsed ? sources.byId(parsed.source.id) : undefined;
  const unconnected = state !== undefined && state.status !== "connected";
  const kind =
    parsed && parsed.item.label !== link.title ? parsed.item.label : null;
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
          <SourceLogo source={parsed.source} size={15} />
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
        ) : null
      }
      prefix={kind ?? (external ? hostOf(link.target) : null)}
      note={link.note}
      onNoteChange={
        unconnected && warning
          ? undefined
          : (note) => onChange({ ...link, note })
      }
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

function KnowledgeRow({
  icon,
  title,
  meta,
  prefix = null,
  note = "",
  onNoteChange,
  onOpen,
  onRemove,
  actions,
  trailing,
  disabled = false,
}: {
  icon: ReactNode;
  title: string;
  /** A fixed second line. Ignored when the note is editable. */
  meta?: ReactNode;
  /** What the row is, shown before the person's note. */
  prefix?: string | null;
  note?: string;
  onNoteChange?: (note: string) => Promise<void>;
  onOpen: (() => void) | null;
  onRemove?: () => void;
  /** Controls that stay visible; the remove button only shows on hover. */
  actions?: ReactNode;
  trailing: ReactNode;
  disabled?: boolean;
}) {
  return (
    <div className="group/row relative flex items-center gap-3 rounded-md px-3 py-2.5 transition-colors hover:bg-fill-hover">
      <span className="flex size-[18px] shrink-0 items-center justify-center text-muted-foreground">
        {icon}
      </span>
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        {onOpen ? (
          <button
            type="button"
            onClick={onOpen}
            className="truncate text-left font-medium text-foreground text-sm after:absolute after:inset-0 after:content-['']"
          >
            {title}
          </button>
        ) : (
          <span className="truncate font-medium text-foreground text-sm">
            {title}
          </span>
        )}
        {onNoteChange ? (
          <span className="relative z-10 flex min-w-0">
            <EditableNote
              prefix={prefix}
              note={note}
              onSave={onNoteChange}
              disabled={disabled}
            />
          </span>
        ) : meta ? (
          <span className="truncate text-muted-foreground text-xs">{meta}</span>
        ) : null}
      </span>
      <span className="relative z-10 flex shrink-0 items-center gap-1">
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

function hostOf(url: string): string {
  try {
    return new URL(url).host.replace(/^www\./, "");
  } catch {
    return url;
  }
}
