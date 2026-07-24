import { CaretDown, Hash, Lock } from "@phosphor-icons/react";
import {
  buildChannelTargetValue,
  mergeVisibleChannels,
  parseChannelIdFromTargetValue,
  parseChannelNameFromTargetValue,
} from "@posthog/core/settings/slackNotificationTarget";
import {
  Button,
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
  ComboboxTrigger,
} from "@posthog/quill";
import { useSlackChannels } from "@posthog/ui/features/inbox/hooks/useSlackChannels";
import { ModalInlineComboboxContent } from "@posthog/ui/features/settings/ModalInlineComboboxContent";
import { useDebouncedValue } from "@posthog/ui/primitives/hooks/useDebouncedValue";
import { useMemo, useRef, useState } from "react";

const OFF_VALUE = "__off__";
const SLACK_CHANNEL_SEARCH_DEBOUNCE_MS = 300;
const CONTROL_CLASS = "min-w-[200px] max-w-[240px]";

interface SlackChannelComboboxProps {
  /** Workspace whose channels we list. Channels can't be picked without one. */
  integrationId: number | null;
  /** Current `channel_id|#channel-name` target, or null when nothing is set. */
  value: string | null;
  /** Fires with a new target, or null when "off" is chosen. */
  onChange: (channelTarget: string | null) => void;
  /** When set, includes an option that clears the selected channel. */
  offLabel?: string;
  ariaLabel: string;
  modal?: boolean;
  disabled?: boolean;
}

export function SlackChannelCombobox({
  integrationId,
  value,
  onChange,
  offLabel,
  ariaLabel,
  modal = false,
  disabled = false,
}: SlackChannelComboboxProps) {
  const selectedChannelId = parseChannelIdFromTargetValue(value);
  const selectedChannelName = parseChannelNameFromTargetValue(value);
  const hasChannel = !!value;

  const anchorRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const { debounced: debouncedSearch, isPending: searchDebouncing } =
    useDebouncedValue(searchQuery.trim(), SLACK_CHANNEL_SEARCH_DEBOUNCE_MS);

  const { data: channelsData, isFetching } = useSlackChannels(integrationId, {
    search: debouncedSearch || undefined,
  });
  const initialLoading = !!integrationId && !channelsData && isFetching;
  const searchPending = open && (isFetching || searchDebouncing);

  const visibleChannels = useMemo(
    () =>
      mergeVisibleChannels(
        channelsData?.channels ?? [],
        selectedChannelId,
        selectedChannelName,
      ),
    [channelsData?.channels, selectedChannelId, selectedChannelName],
  );

  const comboboxItems = useMemo(
    () => [
      ...(offLabel ? [OFF_VALUE] : []),
      ...visibleChannels.map((c) => c.id),
    ],
    [offLabel, visibleChannels],
  );
  const triggerLabel = (() => {
    if ((initialLoading || searchPending) && !hasChannel) {
      return "Loading channels…";
    }
    if (selectedChannelName) return selectedChannelName;
    if (selectedChannelId) return selectedChannelId;
    return "Pick a channel";
  })();

  const comboboxValue = (() => {
    if (hasChannel && selectedChannelId) return selectedChannelId;
    if (offLabel) return OFF_VALUE;
    return null;
  })();

  const onComboboxChange = (rawValue: string | null) => {
    setOpen(false);
    setSearchQuery("");
    if (rawValue === null) return;
    if (rawValue === OFF_VALUE) {
      onChange(null);
      return;
    }
    if (!integrationId) return;
    const channel = visibleChannels.find((c) => c.id === rawValue);
    if (!channel) return;
    onChange(buildChannelTargetValue(channel.id, channel.name));
  };

  const panel = (
    <>
      <ComboboxInput placeholder="Search channels…" showTrigger={false} />
      <ComboboxEmpty>
        {searchPending
          ? "Loading channels…"
          : "No channels match — make sure PostHog is in the channel."}
      </ComboboxEmpty>
      <ComboboxList className="max-h-[min(18rem,calc(var(--available-height,18rem)-5rem))]">
        {(itemValue: string) => {
          if (itemValue === OFF_VALUE) {
            if (!offLabel) return null;
            return (
              <ComboboxItem key={OFF_VALUE} value={OFF_VALUE} title={offLabel}>
                {offLabel}
              </ComboboxItem>
            );
          }
          const channel = visibleChannels.find((c) => c.id === itemValue);
          if (!channel) return null;
          const Icon = channel.is_private ? Lock : Hash;
          return (
            <ComboboxItem
              key={channel.id}
              value={channel.id}
              title={channel.name}
            >
              <Icon size={12} weight="regular" className="shrink-0" />
              <span className="min-w-0 truncate">{channel.name}</span>
              {channel.is_ext_shared ? (
                <span className="ms-1 shrink-0 text-muted-foreground text-xs">
                  (shared)
                </span>
              ) : null}
            </ComboboxItem>
          );
        }}
      </ComboboxList>
    </>
  );

  const popupProps = {
    anchor: anchorRef,
    side: "bottom" as const,
    sideOffset: 4,
    className: "min-w-[240px]",
  };

  return (
    <div ref={anchorRef} className="inline-flex">
      <Combobox
        items={comboboxItems}
        filter={null}
        value={comboboxValue}
        onValueChange={(v) => onComboboxChange(v as string | null)}
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          if (!next) setSearchQuery("");
        }}
        inputValue={searchQuery}
        onInputValueChange={(v) => setSearchQuery(v ?? "")}
        disabled={disabled || !integrationId}
        modal={false}
      >
        <ComboboxTrigger
          render={
            <Button
              variant="outline"
              size="sm"
              disabled={disabled || !integrationId}
              aria-label={ariaLabel}
              aria-busy={initialLoading || searchPending}
              className={`${CONTROL_CLASS} justify-between`}
            >
              <span className="flex min-w-0 items-center gap-1">
                {hasChannel && selectedChannelId ? (
                  <Hash size={12} weight="regular" className="shrink-0" />
                ) : null}
                <span className="min-w-0 truncate">{triggerLabel}</span>
              </span>
              <CaretDown
                size={10}
                weight="bold"
                className="shrink-0 text-muted-foreground"
              />
            </Button>
          }
        />
        {modal ? (
          <ModalInlineComboboxContent {...popupProps}>
            {panel}
          </ModalInlineComboboxContent>
        ) : (
          <ComboboxContent {...popupProps}>{panel}</ComboboxContent>
        )}
      </Combobox>
    </div>
  );
}
