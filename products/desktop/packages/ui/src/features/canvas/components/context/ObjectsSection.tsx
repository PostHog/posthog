import {
  ArrowSquareOutIcon,
  BugIcon,
  ChartBarIcon,
  ChatsCircleIcon,
  CursorClickIcon,
  FlagIcon,
  FlaskIcon,
  LightningIcon,
  LinkIcon,
  NotebookIcon,
  PlayCircleIcon,
  PlusIcon,
  SquaresFourIcon,
  TrashIcon,
  UserIcon,
  UsersThreeIcon,
} from "@phosphor-icons/react";
import {
  CONTEXT_OBJECT_KIND_LABELS,
  type ContextObject,
  type ContextObjectKind,
  isHttpUrl,
  parsePostHogObjectUrl,
} from "@posthog/core/canvas/contextDocument";
import {
  Badge,
  Button,
  Input,
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemMedia,
  ItemTitle,
  Text,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { type ReactNode, useMemo, useState } from "react";
import { SectionCard, SectionPlaceholder } from "./SectionCard";

interface ObjectsSectionProps {
  objects: ContextObject[];
  onChange: (objects: ContextObject[]) => Promise<void>;
  isSaving: boolean;
}

const KIND_ICONS: Record<ContextObjectKind, ReactNode> = {
  insight: <ChartBarIcon size={16} />,
  dashboard: <SquaresFourIcon size={16} />,
  flag: <FlagIcon size={16} />,
  experiment: <FlaskIcon size={16} />,
  survey: <ChatsCircleIcon size={16} />,
  error: <BugIcon size={16} />,
  replay: <PlayCircleIcon size={16} />,
  notebook: <NotebookIcon size={16} />,
  cohort: <UsersThreeIcon size={16} />,
  action: <CursorClickIcon size={16} />,
  person: <UserIcon size={16} />,
  event: <LightningIcon size={16} />,
  link: <LinkIcon size={16} />,
};

const KIND_ORDER: ContextObjectKind[] = [
  "dashboard",
  "insight",
  "flag",
  "experiment",
  "survey",
  "error",
  "cohort",
  "action",
  "event",
  "notebook",
  "replay",
  "person",
  "link",
];

/** The flags, insights, dashboards, and other PostHog objects this space is about. */
export function ObjectsSection({
  objects,
  onChange,
  isSaving,
}: ObjectsSectionProps) {
  const [adding, setAdding] = useState(false);
  const showForm = adding || objects.length === 0;

  const sorted = useMemo(
    () =>
      objects
        .map((object, index) => ({ object, index }))
        .sort(
          (a, b) =>
            KIND_ORDER.indexOf(a.object.kind) -
              KIND_ORDER.indexOf(b.object.kind) || a.index - b.index,
        ),
    [objects],
  );

  const remove = (index: number) =>
    onChange(objects.filter((_, i) => i !== index));

  const add = async (object: ContextObject) => {
    await onChange([...objects, object]);
    setAdding(false);
  };

  return (
    <SectionCard
      icon={<SquaresFourIcon size={16} />}
      title="PostHog objects"
      description="The dashboards, insights, flags, and experiments that belong to this space."
      count={objects.length}
      actions={
        !showForm ? (
          <Button variant="outline" size="sm" onClick={() => setAdding(true)}>
            <PlusIcon size={14} />
            Add
          </Button>
        ) : null
      }
    >
      {objects.length > 0 ? (
        <ul className="-mr-px -mb-px grid @3xl:grid-cols-3 @lg:grid-cols-2">
          {sorted.map(({ object, index }) => (
            <li
              key={`${object.url}-${index}`}
              className="group/object border-border border-r border-b"
            >
              <Item
                variant="default"
                size="sm"
                className="h-full rounded-none border-0 px-4"
              >
                <ItemMedia variant="icon">{KIND_ICONS[object.kind]}</ItemMedia>
                <ItemContent className="min-w-0">
                  <ItemTitle className="truncate">
                    <button
                      type="button"
                      className="truncate text-left hover:underline"
                      onClick={() => openExternalUrl(object.url)}
                    >
                      {object.title}
                    </button>
                  </ItemTitle>
                  <ItemDescription>
                    {CONTEXT_OBJECT_KIND_LABELS[object.kind]}
                  </ItemDescription>
                </ItemContent>
                <ItemActions className="opacity-0 transition-opacity group-focus-within/object:opacity-100 group-hover/object:opacity-100">
                  <Tooltip>
                    <TooltipTrigger
                      render={
                        <Button
                          variant="default"
                          size="icon-xs"
                          aria-label={`Open ${object.title}`}
                          onClick={() => openExternalUrl(object.url)}
                        />
                      }
                    >
                      <ArrowSquareOutIcon size={14} />
                    </TooltipTrigger>
                    <TooltipContent>Open in PostHog</TooltipContent>
                  </Tooltip>
                  <Tooltip>
                    <TooltipTrigger
                      render={
                        <Button
                          variant="default"
                          size="icon-xs"
                          aria-label={`Remove ${object.title}`}
                          disabled={isSaving}
                          onClick={() => void remove(index)}
                        />
                      }
                    >
                      <TrashIcon size={14} />
                    </TooltipTrigger>
                    <TooltipContent>Remove</TooltipContent>
                  </Tooltip>
                </ItemActions>
              </Item>
            </li>
          ))}
        </ul>
      ) : null}

      {showForm ? (
        <AddObjectForm
          onAdd={add}
          onCancel={objects.length > 0 ? () => setAdding(false) : undefined}
          isSaving={isSaving}
        />
      ) : null}
    </SectionCard>
  );
}

function AddObjectForm({
  onAdd,
  onCancel,
  isSaving,
}: {
  onAdd: (object: ContextObject) => Promise<void>;
  onCancel?: () => void;
  isSaving: boolean;
}) {
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const trimmed = url.trim();
  const parsed = useMemo(() => parsePostHogObjectUrl(trimmed), [trimmed]);
  const validUrl = isHttpUrl(trimmed);
  const kind: ContextObjectKind = parsed?.kind ?? "link";
  const suggestedTitle = parsed
    ? `${CONTEXT_OBJECT_KIND_LABELS[parsed.kind]} ${parsed.id}`
    : trimmed;
  const canAdd = validUrl && !isSaving;

  const submit = async () => {
    if (!canAdd) return;
    await onAdd({ kind, url: trimmed, title: title.trim() || suggestedTitle });
    setUrl("");
    setTitle("");
  };

  return (
    <form
      className="flex flex-col gap-2 border-border border-t px-4 py-3 first:border-t-0"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      {onCancel === undefined ? (
        <SectionPlaceholder className="px-0 pt-2 pb-3">
          <Text size="xs" weight="medium">
            No objects linked yet
          </Text>
          <Text size="xs" variant="muted">
            Paste the URL of a dashboard, insight, flag, experiment, survey, or
            error issue from PostHog.
          </Text>
        </SectionPlaceholder>
      ) : null}
      <div className="grid @lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] gap-2">
        <div className="flex items-center gap-2">
          <Input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://us.posthog.com/project/…/insights/…"
            aria-label="PostHog object URL"
            autoFocus={onCancel !== undefined}
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
          placeholder={parsed ? suggestedTitle : "Title (optional)"}
          aria-label="Title"
        />
      </div>
      <div className="flex items-center justify-end gap-2">
        {onCancel ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onCancel}
            disabled={isSaving}
          >
            Cancel
          </Button>
        ) : null}
        <Button type="submit" variant="primary" size="sm" disabled={!canAdd}>
          <PlusIcon size={14} />
          Add
        </Button>
      </div>
    </form>
  );
}
