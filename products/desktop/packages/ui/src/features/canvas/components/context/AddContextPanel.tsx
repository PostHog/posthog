import { FileTextIcon, LinkIcon, XIcon } from "@phosphor-icons/react";
import {
  CONTEXT_OBJECT_KIND_LABELS,
  type ContextLink,
  type ContextObject,
  isHttpUrl,
  parsePostHogObjectUrl,
} from "@posthog/core/canvas/contextDocument";
import { parseContextSourceInput } from "@posthog/core/canvas/contextSources";
import { Button, cn, Input, Text } from "@posthog/quill";
import {
  type ContextSourceState,
  useContextSources,
} from "@posthog/ui/features/canvas/hooks/useContextSources";
import { ServerIcon } from "@posthog/ui/features/mcp-servers/components/parts/icons";
import { type ReactNode, useMemo, useState } from "react";
import { ConnectSourceCard } from "./ConnectSourceCard";
import { KIND_ICONS } from "./kindIcons";

interface AddContextPanelProps {
  onAddLink: (link: ContextLink) => Promise<void>;
  onAddObject: (object: ContextObject) => Promise<void>;
  onCancel: () => void;
  isSaving: boolean;
}

/** The chip for anything without a source of its own: a link, a repository path, or a PostHog URL. */
const ANY = "any";
const POSTHOG = "posthog";
const POSTHOG_ICON_DOMAIN = "posthog.com";

/**
 * One panel for every kind of context. The chips show where context can come
 * from, including sources that are not connected yet, so a person sees what
 * is possible before they paste anything. A pasted URL picks its own chip.
 * The input reads what it was given: a PostHog URL becomes a live object, a
 * link from a connected source keeps that source's name, and anything else is
 * a link or a repository path.
 */
export function AddContextPanel({
  onAddLink,
  onAddObject,
  onCancel,
  isSaving,
}: AddContextPanelProps) {
  const sources = useContextSources();
  const [picked, setPicked] = useState<string>(ANY);
  const [target, setTarget] = useState("");
  const [note, setNote] = useState("");
  const trimmed = target.trim();

  const pickedState = picked === ANY ? null : sources.byId(picked);
  const object = useMemo(() => parsePostHogObjectUrl(trimmed), [trimmed]);
  const external = useMemo(
    () =>
      object
        ? null
        : parseContextSourceInput(trimmed, pickedState?.source ?? null),
    [trimmed, object, pickedState],
  );
  // A link from a source that has a chip belongs to that chip, even when the
  // person pasted it under "Link or file"; that is how an unconnected source
  // gets to show its connect step instead of taking a link agents cannot read.
  const externalState = external ? sources.byId(external.source.id) : null;
  const activeState = externalState ?? pickedState ?? null;
  const blocked = activeState !== null && activeState.status !== "connected";

  const detected: { icon: ReactNode; label: string } | null = !trimmed
    ? null
    : object
      ? {
          icon: KIND_ICONS[object.kind],
          label: CONTEXT_OBJECT_KIND_LABELS[object.kind],
        }
      : external
        ? {
            icon: (
              <ServerIcon iconDomain={external.source.iconDomain} size={15} />
            ),
            label: external.item.label,
          }
        : pickedState
          ? null
          : isHttpUrl(trimmed)
            ? { icon: <LinkIcon size={15} />, label: "Link" }
            : { icon: <FileTextIcon size={15} />, label: "Repository file" };

  const canAdd = detected !== null && !blocked && !isSaving;

  const submit = async () => {
    if (!canAdd) return;
    if (object) {
      await onAddObject({
        kind: object.kind,
        url: trimmed,
        title:
          note.trim() ||
          `${CONTEXT_OBJECT_KIND_LABELS[object.kind]} ${object.id}`,
      });
      return;
    }
    if (external) {
      await onAddLink({
        target: external.item.target,
        title: external.item.title,
        note: note.trim(),
      });
      return;
    }
    await onAddLink({
      target: trimmed,
      title: titleFromTarget(trimmed),
      note: note.trim(),
    });
  };

  const placeholder = pickedState
    ? pickedState.source.placeholder
    : picked === POSTHOG
      ? "Paste the URL of an insight, dashboard, flag, experiment, or any PostHog object"
      : "Paste a PostHog URL, a link, or a repository path";

  const hint = blocked
    ? null
    : pickedState
      ? `${pickedState.source.name} is connected. ${pickedState.source.purpose}`
      : picked === POSTHOG
        ? "Linked objects show their live state here and route reports about them to this space."
        : "A PostHog URL becomes a live object. A link from a connected source keeps its name.";

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-border bg-card p-4 shadow-sm">
      <div className="flex items-center justify-between gap-2">
        <Text size="xs" weight="medium">
          Add context
        </Text>
        <Button
          variant="default"
          size="icon-xs"
          aria-label="Close"
          onClick={onCancel}
          className="text-muted-foreground"
        >
          <XIcon size={13} />
        </Button>
      </div>

      <div className="flex flex-wrap gap-1.5">
        <SourceChip
          icon={<LinkIcon size={13} />}
          label="Link or file"
          selected={activeState === null && picked === ANY}
          onSelect={() => setPicked(ANY)}
        />
        <SourceChip
          icon={<ServerIcon iconDomain={POSTHOG_ICON_DOMAIN} size={13} />}
          label="PostHog"
          selected={activeState === null && picked === POSTHOG}
          onSelect={() => setPicked(POSTHOG)}
        />
        {sources.sources.map((state) => (
          <SourceChip
            key={state.source.id}
            icon={<ServerIcon iconDomain={state.source.iconDomain} size={13} />}
            label={state.source.name}
            status={state.status}
            selected={activeState?.source.id === state.source.id}
            onSelect={() => setPicked(state.source.id)}
          />
        ))}
      </div>

      {blocked && activeState ? (
        <ConnectSourceCard
          state={activeState}
          onConnect={() => sources.connect(activeState)}
          heldLink={external ? trimmed : null}
        />
      ) : (
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
              {detected?.icon ??
                (pickedState ? (
                  <ServerIcon
                    iconDomain={pickedState.source.iconDomain}
                    size={15}
                  />
                ) : (
                  <LinkIcon size={15} />
                ))}
            </span>
            <Input
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              placeholder={placeholder}
              aria-label={placeholder}
              autoFocus
              className="min-w-0 flex-1 font-mono text-xs"
            />
            {detected ? (
              <Text size="xxs" variant="muted" className="shrink-0">
                {detected.label}
              </Text>
            ) : null}
          </div>
          <div className="flex items-center gap-2 pl-[26px]">
            <Input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder={
                object
                  ? "Name (optional)"
                  : "Why it matters, in a few words (optional)"
              }
              aria-label={object ? "Name" : "Why it matters"}
              className="min-w-0 flex-1"
            />
          </div>
          <div className="flex items-center justify-between gap-3 pt-1 pl-[26px]">
            <Text size="xxs" variant="muted" className="min-w-0">
              {trimmed && !detected && pickedState
                ? `Paste a link from ${pickedState.source.name}.`
                : hint}
            </Text>
            <div className="flex shrink-0 items-center gap-1">
              <Button
                type="button"
                variant="link-muted"
                size="xs"
                onClick={onCancel}
                disabled={isSaving}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                variant="primary"
                size="xs"
                disabled={!canAdd}
              >
                Add
              </Button>
            </div>
          </div>
        </form>
      )}
    </div>
  );
}

const STATUS_DOT: Record<ContextSourceState["status"], string | null> = {
  connected: "bg-success-foreground",
  needs_reauth: "bg-warning-foreground",
  pending_oauth: "bg-warning-foreground",
  not_connected: null,
};

/** One place context can come from. The dot says its server is connected; no dot means connecting comes first. */
function SourceChip({
  icon,
  label,
  status,
  selected,
  onSelect,
}: {
  icon: ReactNode;
  label: string;
  status?: ContextSourceState["status"];
  selected: boolean;
  onSelect: () => void;
}) {
  const dot = status ? STATUS_DOT[status] : null;
  const unconnected = status !== undefined && status === "not_connected";
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onSelect}
      className={cn(
        "flex h-7 items-center gap-1.5 rounded-md border px-2 text-xs transition-colors",
        selected
          ? "border-foreground/30 bg-fill-hover text-foreground"
          : "border-border text-muted-foreground hover:bg-fill-hover hover:text-foreground",
      )}
    >
      <span
        className={cn(
          "flex size-[13px] items-center justify-center",
          unconnected && !selected && "opacity-60 grayscale",
        )}
      >
        {icon}
      </span>
      <span className="font-medium">{label}</span>
      {dot ? (
        <span className={cn("size-1.5 rounded-full", dot)} aria-hidden="true" />
      ) : null}
    </button>
  );
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
