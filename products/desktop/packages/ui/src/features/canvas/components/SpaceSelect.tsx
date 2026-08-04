import {
  Button,
  Combobox,
  ComboboxCollection,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxGroup,
  ComboboxInput,
  ComboboxItem,
  ComboboxLabel,
  ComboboxList,
  ComboboxSeparator,
  ComboboxTrigger,
} from "@posthog/quill";
import { channelGlyph } from "@posthog/ui/features/canvas/components/channelGlyph";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useMemo, useRef } from "react";

interface SpaceGroup {
  value: string;
  items: string[];
}

/**
 * Which space a new task files into — a chip for the composer's selector row,
 * drawn like the EnvironmentSelector and WorkspaceModeSelect beside it. A
 * project can carry hundreds of spaces, so the list is searchable: starred
 * spaces (with #me leading) sit above the rest, under the same "Starred" /
 * "Spaces" headings the sidebar list uses.
 */
export function SpaceSelect({
  value,
  onChange,
}: {
  value: string;
  onChange: (channelId: string) => void;
}) {
  const { channels } = useChannels();
  const anchorRef = useRef<HTMLDivElement>(null);
  const current = channels.find((c) => c.id === value) ?? null;

  const byId = useMemo(
    () => new Map(channels.map((c) => [c.id, c])),
    [channels],
  );

  // Ids, not Channel objects: the channels query repolls and rebuilds its
  // objects, so a selected object stops matching the list by identity and the
  // combobox silently drops the selection. Ids compare by value.
  //
  // `useChannels` already sorts by name, so both groups stay alphabetical
  // without re-sorting; #me leads because it's where an unfiled task goes.
  // An empty group is dropped rather than rendered as a bare heading.
  const groups = useMemo<SpaceGroup[]>(() => {
    const starred = channels.filter(
      (c) => c.channelType === "personal" || c.starred,
    );
    const rest = channels.filter(
      (c) => c.channelType !== "personal" && !c.starred,
    );
    return [
      { value: "Starred", items: starred.map((c) => c.id) },
      { value: "Spaces", items: rest.map((c) => c.id) },
    ].filter((group) => group.items.length > 0);
  }, [channels]);

  const triggerGlyph = channelGlyph(current?.name, { size: 14, space: true });

  return (
    <Combobox<string>
      items={groups}
      value={value}
      onValueChange={(nextId) => {
        if (nextId && nextId !== value) onChange(nextId);
      }}
      itemToStringLabel={(id) => byId.get(id)?.name ?? ""}
    >
      <div ref={anchorRef} className="inline-flex">
        <ComboboxTrigger
          render={
            <Button
              type="button"
              variant="default"
              size="sm"
              aria-label="Space"
              title={current?.name}
            >
              {triggerGlyph && (
                <span className="shrink-0 text-muted-foreground">
                  {triggerGlyph}
                </span>
              )}
              <span className="min-w-0 truncate">
                {current?.name ?? "Space"}
              </span>
            </Button>
          }
        />
      </div>
      <ComboboxContent
        anchor={anchorRef}
        side="bottom"
        sideOffset={6}
        className="min-w-[220px]"
      >
        <ComboboxInput placeholder="Search spaces..." showTrigger={false} />
        <ComboboxEmpty>No spaces found.</ComboboxEmpty>
        <ComboboxList className="max-h-[min(18rem,calc(var(--available-height,18rem)-5rem))]">
          {(group: SpaceGroup, index: number) => (
            <ComboboxGroup key={group.value} items={group.items}>
              <ComboboxLabel>{group.value}</ComboboxLabel>
              <ComboboxCollection>
                {(id: string) => {
                  const space = byId.get(id);
                  if (!space) return null;
                  return (
                    <ComboboxItem
                      key={id}
                      value={id}
                      title={space.name}
                      className="relative"
                    >
                      {channelGlyph(space.name, { size: 14, space: true })}
                      {space.name}
                    </ComboboxItem>
                  );
                }}
              </ComboboxCollection>
              {index < groups.length - 1 && <ComboboxSeparator />}
            </ComboboxGroup>
          )}
        </ComboboxList>
      </ComboboxContent>
    </Combobox>
  );
}
