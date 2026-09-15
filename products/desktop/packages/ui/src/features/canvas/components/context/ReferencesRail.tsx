import {
  ArrowSquareOutIcon,
  BugIcon,
  ChartBarIcon,
  ChatsCircleIcon,
  CursorClickIcon,
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
import { Badge, Button, cn, Input, Text } from "@posthog/quill";
import { useWatchedObjectPreview } from "@posthog/ui/features/canvas/hooks/useWatchedObjectPreview";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { type ReactNode, useMemo, useState } from "react";

interface ReferencesRailProps {
  links: ContextLink[];
  objects: ContextObject[];
  onLinksChange: (links: ContextLink[]) => Promise<void>;
  onObjectsChange: (objects: ContextObject[]) => Promise<void>;
  isSaving: boolean;
}

/**
 * The rail groups linked objects by the work a person or an agent does with
 * them, not by product type. The type stays on the row as a small label.
 * "Reading" is the first group and holds docs and files; these hold the rest.
 */
const JOB_GROUPS: {
  title: string;
  hint: string;
  kinds: ContextObjectKind[];
}[] = [
  {
    title: "Measuring",
    hint: "dashboards, insights",
    kinds: ["dashboard", "insight", "cohort", "action", "event"],
  },
  {
    title: "Shipping",
    hint: "flags, experiments",
    kinds: ["flag", "experiment"],
  },
  { title: "Fixing", hint: "error issues", kinds: ["error"] },
  { title: "Listening", hint: "surveys, replays", kinds: ["survey", "replay"] },
];

/** Objects that read like documents sit with the docs, not with the live objects. */
const READING_KINDS: ContextObjectKind[] = ["notebook", "link", "person"];

/**
 * What agents read, measure, ship, fix, and listen to in this space. Docs and
 * files first, then the linked objects by the work done with them, each with
 * its live state.
 */
export function ReferencesRail({
  links,
  objects,
  onLinksChange,
  onObjectsChange,
  isSaving,
}: ReferencesRailProps) {
  const [linking, setLinking] = useState(false);
  const indexed = useMemo(
    () => objects.map((object, index) => ({ object, index })),
    [objects],
  );
  const readingObjects = indexed.filter(({ object }) =>
    READING_KINDS.includes(object.kind),
  );
  const groups = JOB_GROUPS.map((group) => ({
    ...group,
    items: indexed.filter(({ object }) => group.kinds.includes(object.kind)),
  })).filter((group) => group.items.length > 0);

  const removeObject = (index: number) =>
    onObjectsChange(objects.filter((_, i) => i !== index));

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <RailGroup
        title="Reading"
        hint="docs, files"
        count={links.length + readingObjects.length}
        emptyHint="Specs, docs, and repository files agents should read."
        isSaving={isSaving}
        renderForm={(close) => (
          <AddLinkForm
            isSaving={isSaving}
            onAdd={async (link) => {
              await onLinksChange([...links, link]);
              close();
            }}
            onCancel={close}
          />
        )}
      >
        {links.map((link, index) => {
          const external = isHttpUrl(link.target);
          return (
            <RailRow
              key={`${link.target}-${index}`}
              icon={
                external ? <LinkIcon size={14} /> : <FileTextIcon size={14} />
              }
              title={link.title}
              detail={link.note || (external ? hostOf(link.target) : null)}
              mono={!external && !link.note}
              onOpen={external ? () => openExternalUrl(link.target) : null}
              onRemove={() =>
                onLinksChange(links.filter((_, i) => i !== index))
              }
              disabled={isSaving}
            />
          );
        })}
        {readingObjects.map(({ object, index }) => (
          <WatchedRow
            key={`${object.url}-${index}`}
            object={object}
            onRemove={() => removeObject(index)}
            disabled={isSaving}
          />
        ))}
      </RailGroup>

      {groups.map((group) => (
        <section key={group.title} className="flex flex-col gap-1.5">
          <GroupHeading
            title={group.title}
            hint={group.hint}
            count={group.items.length}
          />
          <ul className="-mx-2 flex flex-col">
            {group.items.map(({ object, index }) => (
              <WatchedRow
                key={`${object.url}-${index}`}
                object={object}
                onRemove={() => removeObject(index)}
                disabled={isSaving}
              />
            ))}
          </ul>
        </section>
      ))}

      {linking ? (
        <AddObjectForm
          isSaving={isSaving}
          onAdd={async (object) => {
            await onObjectsChange([...objects, object]);
            setLinking(false);
          }}
          onCancel={() => setLinking(false)}
        />
      ) : (
        <Button
          variant="link-muted"
          size="xs"
          className="self-start"
          disabled={isSaving}
          onClick={() => setLinking(true)}
        >
          <PlusIcon size={12} />
          {objects.length === 0
            ? "Link what this space owns"
            : "Link a dashboard, flag, experiment, or error issue"}
        </Button>
      )}
    </div>
  );
}

function GroupHeading({
  title,
  hint,
  count,
}: {
  title: string;
  hint: string;
  count: number;
}) {
  return (
    <Text size="xs" weight="medium" variant="muted" title={hint}>
      {title}
      {count > 0 ? (
        <span className="ml-1.5 font-normal tabular-nums">{count}</span>
      ) : null}
    </Text>
  );
}

function RailGroup({
  title,
  hint,
  count,
  emptyHint,
  isSaving,
  renderForm,
  children,
}: {
  title: string;
  hint: string;
  count: number;
  emptyHint: string;
  isSaving: boolean;
  renderForm: (close: () => void) => ReactNode;
  children: ReactNode;
}) {
  const [adding, setAdding] = useState(false);
  return (
    <section className="flex flex-col gap-1.5">
      <GroupHeading title={title} hint={hint} count={count} />
      {count > 0 ? (
        <ul className="-mx-2 flex flex-col">{children}</ul>
      ) : !adding ? (
        <Text size="xxs" variant="muted">
          {emptyHint}
        </Text>
      ) : null}
      {adding ? (
        renderForm(() => setAdding(false))
      ) : (
        <Button
          variant="link-muted"
          size="xs"
          className="self-start"
          disabled={isSaving}
          onClick={() => setAdding(true)}
        >
          <PlusIcon size={12} />
          Add a doc or file
        </Button>
      )}
    </section>
  );
}

const TONE_DOT: Record<string, string> = {
  positive: "bg-success-foreground",
  neutral: "bg-muted-foreground/50",
  caution: "bg-warning-foreground",
  critical: "bg-destructive",
};

/** A linked object with its live state: rollout, status, volume. */
function WatchedRow({
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
  const live =
    data?.status || facts.length > 0 ? (
      <span className="flex items-center gap-1.5">
        {data?.status ? (
          <>
            <span
              className={cn(
                "size-1.5 shrink-0 rounded-full",
                TONE_DOT[data.status.tone] ?? TONE_DOT.neutral,
              )}
            />
            <span>{data.status.label}</span>
          </>
        ) : null}
        {facts.map((fact) => (
          <span key={fact}>{`· ${fact}`}</span>
        ))}
      </span>
    ) : null;
  return (
    <RailRow
      icon={KIND_ICONS[object.kind]}
      title={data?.title || object.title}
      detail={CONTEXT_OBJECT_KIND_LABELS[object.kind]}
      live={live}
      onOpen={() => openExternalUrl(object.url)}
      onRemove={onRemove}
      disabled={disabled}
    />
  );
}

function RailRow({
  icon,
  title,
  detail,
  live,
  mono = false,
  onOpen,
  onRemove,
  disabled,
}: {
  icon: ReactNode;
  title: string;
  detail: string | null;
  /** The object's current state, when it has one. */
  live?: ReactNode;
  mono?: boolean;
  onOpen: (() => void) | null;
  onRemove: () => void;
  disabled: boolean;
}) {
  const body = (
    <>
      <span className="mt-0.5 shrink-0 text-muted-foreground">{icon}</span>
      <span className="flex min-w-0 flex-1 flex-col">
        <span
          className={cn(
            "truncate text-foreground text-xs",
            onOpen && "group-hover/row:underline",
          )}
        >
          {title}
        </span>
        {live ? (
          <span className="truncate text-muted-foreground text-xxs">
            {live}
          </span>
        ) : detail ? (
          <span
            className={cn(
              "truncate text-muted-foreground text-xxs",
              mono && "font-mono",
            )}
          >
            {detail}
          </span>
        ) : null}
      </span>
    </>
  );
  return (
    <li className="group/row flex items-start gap-2 rounded-md px-2 py-1.5 hover:bg-fill-hover">
      {onOpen ? (
        <button
          type="button"
          onClick={onOpen}
          className="flex min-w-0 flex-1 items-start gap-2 text-left"
        >
          {body}
        </button>
      ) : (
        <span className="flex min-w-0 flex-1 items-start gap-2">{body}</span>
      )}
      <span className="flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity group-focus-within/row:opacity-100 group-hover/row:opacity-100">
        {onOpen ? (
          <Button
            variant="default"
            size="icon-xs"
            aria-label={`Open ${title}`}
            onClick={onOpen}
          >
            <ArrowSquareOutIcon size={13} />
          </Button>
        ) : null}
        <Button
          variant="default"
          size="icon-xs"
          aria-label={`Remove ${title}`}
          disabled={disabled}
          onClick={() => void onRemove()}
        >
          <XIcon size={13} />
        </Button>
      </span>
    </li>
  );
}

function AddLinkForm({
  onAdd,
  onCancel,
  isSaving,
}: {
  onAdd: (link: ContextLink) => Promise<void>;
  onCancel: () => void;
  isSaving: boolean;
}) {
  const [target, setTarget] = useState("");
  const [note, setNote] = useState("");
  const trimmed = target.trim();
  const canAdd = trimmed.length > 0 && !isSaving;

  return (
    <form
      className="flex flex-col gap-1.5 rounded-md border border-border bg-card p-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (!canAdd) return;
        void onAdd({
          target: trimmed,
          title: titleFromTarget(trimmed),
          note: note.trim(),
        });
      }}
    >
      <Input
        value={target}
        onChange={(e) => setTarget(e.target.value)}
        placeholder="https://… or docs/architecture.md"
        aria-label="URL or repository path"
        autoFocus
        className="font-mono text-xs"
      />
      <Input
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="Why it matters (optional)"
        aria-label="Note"
      />
      <FormActions
        canAdd={canAdd}
        label="Add"
        onCancel={onCancel}
        isSaving={isSaving}
      />
    </form>
  );
}

function AddObjectForm({
  onAdd,
  onCancel,
  isSaving,
}: {
  onAdd: (object: ContextObject) => Promise<void>;
  onCancel: () => void;
  isSaving: boolean;
}) {
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const trimmed = url.trim();
  const parsed = useMemo(() => parsePostHogObjectUrl(trimmed), [trimmed]);
  const validUrl = isHttpUrl(trimmed);
  const suggestedTitle = parsed
    ? `${CONTEXT_OBJECT_KIND_LABELS[parsed.kind]} ${parsed.id}`
    : trimmed;
  const canAdd = validUrl && !isSaving;

  return (
    <form
      className="flex flex-col gap-1.5 rounded-md border border-border bg-card p-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (!canAdd) return;
        void onAdd({
          kind: parsed?.kind ?? "link",
          url: trimmed,
          title: title.trim() || suggestedTitle,
        });
      }}
    >
      <div className="flex items-center gap-1.5">
        <Input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="Paste the link to a dashboard, flag, experiment, or error issue"
          aria-label="Link to a dashboard, flag, experiment, or error issue"
          autoFocus
          className="min-w-0 flex-1 font-mono text-xs"
        />
        {trimmed ? (
          <Badge variant={parsed ? "info" : validUrl ? "default" : "warning"}>
            {parsed
              ? CONTEXT_OBJECT_KIND_LABELS[parsed.kind]
              : validUrl
                ? "Link"
                : "Not a URL"}
          </Badge>
        ) : null}
      </div>
      <Input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder={parsed ? suggestedTitle : "Name (optional)"}
        aria-label="Name"
      />
      <FormActions
        canAdd={canAdd}
        label="Link"
        onCancel={onCancel}
        isSaving={isSaving}
      />
    </form>
  );
}

function FormActions({
  canAdd,
  label,
  onCancel,
  isSaving,
}: {
  canAdd: boolean;
  label: string;
  onCancel: () => void;
  isSaving: boolean;
}) {
  return (
    <div className="flex items-center justify-end gap-1">
      <Button
        type="button"
        variant="outline"
        size="xs"
        onClick={onCancel}
        disabled={isSaving}
      >
        Cancel
      </Button>
      <Button type="submit" variant="primary" size="xs" disabled={!canAdd}>
        {label}
      </Button>
    </div>
  );
}

const KIND_ICONS: Record<ContextObjectKind, ReactNode> = {
  insight: <ChartBarIcon size={14} />,
  dashboard: <SquaresFourIcon size={14} />,
  flag: <FlagIcon size={14} />,
  experiment: <FlaskIcon size={14} />,
  survey: <ChatsCircleIcon size={14} />,
  error: <BugIcon size={14} />,
  replay: <PlayCircleIcon size={14} />,
  notebook: <NotebookIcon size={14} />,
  cohort: <UsersThreeIcon size={14} />,
  action: <CursorClickIcon size={14} />,
  person: <UserIcon size={14} />,
  event: <LightningIcon size={14} />,
  link: <LinkIcon size={14} />,
};

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
