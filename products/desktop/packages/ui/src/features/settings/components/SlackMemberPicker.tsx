import { CaretDownIcon, UserIcon, XIcon } from "@phosphor-icons/react";
import { ApiRequestError } from "@posthog/api-client/fetcher";
import {
  buildMemberTargetValue,
  mergeVisibleMembers,
  parseMemberIdFromTargetValue,
} from "@posthog/core/scouts/scoutSlackDestination";
import {
  Button,
  Chip,
  ChipClose,
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
  ComboboxTrigger,
} from "@posthog/quill";
import { useSlackUsers } from "@posthog/ui/features/inbox/hooks/useSlackUsers";
import { ModalInlineComboboxContent } from "@posthog/ui/features/settings/ModalInlineComboboxContent";
import { useDebouncedValue } from "@posthog/ui/primitives/hooks/useDebouncedValue";
import { useMemo, useRef, useState } from "react";

const SLACK_MEMBER_SEARCH_DEBOUNCE_MS = 300;

/**
 * A failed member fetch must not read as an empty workspace. Surface the
 * server's own message — for an inactive or under-scoped Slack install the
 * backend returns reconnect guidance — so the picker names the real cause.
 */
export function slackMemberErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    const detail = (error.body as { detail?: unknown } | null)?.detail;
    if (typeof detail === "string" && detail) return detail;
  }
  return "Couldn't load members. Try again in a moment.";
}

interface SlackMemberPickerProps {
  /** Workspace whose members we list. Members can't be picked without one. */
  integrationId: number | null;
  /** Selected member targets, each `member_id|@display-name`. */
  value: string[];
  /** Fires with the full next list of targets. */
  onChange: (targets: string[]) => void;
  max: number;
  ariaLabel: string;
  modal?: boolean;
  disabled?: boolean;
}

export function SlackMemberPicker({
  integrationId,
  value,
  onChange,
  max,
  ariaLabel,
  modal = false,
  disabled = false,
}: SlackMemberPickerProps) {
  const anchorRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const { debounced: debouncedSearch, isPending: searchDebouncing } =
    useDebouncedValue(searchQuery.trim(), SLACK_MEMBER_SEARCH_DEBOUNCE_MS);

  const {
    data: usersData,
    isFetching,
    isError,
    error,
  } = useSlackUsers(integrationId, {
    search: debouncedSearch || undefined,
  });
  const searchPending = open && (isFetching || searchDebouncing);

  const selectedIds = useMemo(
    () =>
      new Set(
        value
          .map(parseMemberIdFromTargetValue)
          .filter((id): id is string => id !== null),
      ),
    [value],
  );

  // Chips read their name from the saved target so a member the search page
  // omits still shows a name, not a bare ID.
  const chips = useMemo(() => mergeVisibleMembers([], value), [value]);

  const availableMembers = useMemo(
    () => (usersData?.users ?? []).filter((m) => !selectedIds.has(m.id)),
    [usersData?.users, selectedIds],
  );

  const atLimit = value.length >= max;

  const addMember = (memberId: string) => {
    if (disabled || atLimit || selectedIds.has(memberId)) return;
    const member = availableMembers.find((m) => m.id === memberId);
    if (!member) return;
    onChange([
      ...value,
      buildMemberTargetValue(member.id, member.display_name),
    ]);
    setOpen(false);
    setSearchQuery("");
  };

  const removeMember = (memberId: string) => {
    if (disabled) return;
    onChange(
      value.filter(
        (target) => parseMemberIdFromTargetValue(target) !== memberId,
      ),
    );
  };

  const addDisabledReason = !integrationId
    ? "Pick a workspace first"
    : atLimit
      ? `You can DM up to ${max} people`
      : null;

  const panel = (
    <>
      <ComboboxInput placeholder="Search members…" showTrigger={false} />
      <ComboboxEmpty>
        {searchPending
          ? "Loading members…"
          : isError
            ? slackMemberErrorMessage(error)
            : "No members match"}
      </ComboboxEmpty>
      <ComboboxList className="max-h-[min(18rem,calc(var(--available-height,18rem)-5rem))]">
        {(itemValue: string) => {
          const member = availableMembers.find((m) => m.id === itemValue);
          if (!member) return null;
          // Display names are not unique in a workspace, so surface the unique
          // handle alongside when it differs — otherwise two same-named members
          // are indistinguishable and the wrong one could be DMed.
          const showHandle =
            Boolean(member.name) &&
            member.name.toLowerCase() !== member.display_name.toLowerCase();
          return (
            <ComboboxItem
              key={member.id}
              value={member.id}
              title={
                showHandle
                  ? `${member.display_name} (${member.name})`
                  : member.display_name
              }
            >
              <UserIcon size={12} weight="regular" className="shrink-0" />
              <span className="min-w-0 truncate">{member.display_name}</span>
              {showHandle ? (
                <span className="shrink-0 text-muted-foreground">
                  ({member.name})
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
    <div className="flex min-h-7 w-full max-w-full flex-wrap items-center gap-2">
      {chips.map((member) => (
        <Chip key={member.id}>
          <UserIcon size={13} />
          <span className="max-w-[160px] truncate">{member.display_name}</span>
          <ChipClose
            aria-label={`Remove ${member.display_name}`}
            disabled={disabled}
            onClick={() => removeMember(member.id)}
          >
            <XIcon size={13} weight="bold" />
          </ChipClose>
        </Chip>
      ))}
      {addDisabledReason ? (
        <Button variant="outline" size="sm" disabled aria-label={ariaLabel}>
          <UserIcon size={13} />
          {addDisabledReason}
        </Button>
      ) : (
        <div ref={anchorRef} className="inline-flex">
          <Combobox
            items={availableMembers.map((m) => m.id)}
            filter={null}
            value={null}
            onValueChange={(v) => v != null && addMember(v as string)}
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
                  aria-busy={searchPending}
                  className="justify-between"
                >
                  <span className="flex min-w-0 items-center gap-1">
                    <UserIcon size={13} className="shrink-0" />
                    <span className="min-w-0 truncate">
                      {value.length > 0 ? "Add…" : "Add member…"}
                    </span>
                  </span>
                  <CaretDownIcon
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
      )}
    </div>
  );
}
