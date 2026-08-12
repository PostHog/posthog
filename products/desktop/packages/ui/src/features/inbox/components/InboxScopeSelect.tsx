import { AsteriskSimpleIcon, CaretDownIcon } from "@phosphor-icons/react";
import {
  INBOX_SCOPE_ENTIRE_PROJECT,
  INBOX_SCOPE_FOR_YOU,
  type InboxScope,
  isTeammateInboxScope,
  parseTeammateInboxScope,
  teammateInboxScope,
} from "@posthog/core/inbox/reportMembership";
import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
} from "@posthog/quill";
import { ReviewerAvatar } from "@posthog/ui/features/inbox/components/ReviewerAvatar";
import { getSuggestedReviewerDisplayName } from "@posthog/ui/features/inbox/filterOptions";
import { useInboxScopeOptions } from "@posthog/ui/features/inbox/hooks/useInboxScopeOptions";
import { useInboxReviewerScopeStore } from "@posthog/ui/features/inbox/stores/inboxReviewerScopeStore";
import { SegmentedControl } from "@radix-ui/themes";
import { useMemo, useRef, useState } from "react";

/**
 * Two-segment scope toggle. Left segment is "For you"; right segment shows
 * either "Entire project" or the currently-selected teammate's name, and
 * opens a Quill Combobox with a searchable list of "Entire project + each
 * teammate" when clicked.
 *
 * Segments share equal width – Radix Themes' SegmentedControl indicator is
 * hardcoded to equal-width math (`width: calc(100% / N)` + percentage
 * translate), so a fit-content override desyncs the pill from the items.
 * Keeping the default avoids a custom toggle just for this surface.
 */
const PICKER_ENTIRE_PROJECT_VALUE = "__entire-project__";

type SegmentValue = "for-you" | "entire-project";

export function InboxScopeSelect() {
  const scope = useInboxReviewerScopeStore((s) => s.scope);
  const setScope = useInboxReviewerScopeStore((s) => s.setScope);
  const anchorRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const { teammateOptions } = useInboxScopeOptions();

  const selectedTeammate = useMemo(() => {
    const teammateUuid = parseTeammateInboxScope(scope);
    if (!teammateUuid) return null;
    return (
      teammateOptions.find((option) => option.uuid === teammateUuid) ?? null
    );
  }, [scope, teammateOptions]);

  const segmentValue: SegmentValue =
    scope === INBOX_SCOPE_FOR_YOU ? "for-you" : "entire-project";

  const rightLabel = selectedTeammate
    ? getSuggestedReviewerDisplayName(selectedTeammate)
    : "Entire project";

  const pickerItems = useMemo(() => {
    const items: string[] = [PICKER_ENTIRE_PROJECT_VALUE];
    for (const teammate of teammateOptions) {
      items.push(teammateInboxScope(teammate.uuid));
    }
    return items;
  }, [teammateOptions]);

  const pickerValue: string = isTeammateInboxScope(scope)
    ? scope
    : PICKER_ENTIRE_PROJECT_VALUE;

  const handleSegmentValueChange = (next: string) => {
    if (next === "for-you") {
      setScope(INBOX_SCOPE_FOR_YOU);
      setOpen(false);
    }
  };

  const handlePickerValueChange = (value: unknown) => {
    if (typeof value !== "string") return;
    if (value === PICKER_ENTIRE_PROJECT_VALUE) {
      setScope(INBOX_SCOPE_ENTIRE_PROJECT);
    } else {
      setScope(value as InboxScope);
    }
    setOpen(false);
  };

  return (
    <Combobox
      items={pickerItems}
      value={pickerValue}
      onValueChange={handlePickerValueChange}
      open={open}
      onOpenChange={setOpen}
    >
      <div ref={anchorRef} className="ml-2 inline-flex">
        <SegmentedControl.Root
          value={segmentValue}
          size="1"
          onValueChange={handleSegmentValueChange}
          aria-label="Inbox scope"
        >
          <SegmentedControl.Item value="for-you">For you</SegmentedControl.Item>
          <SegmentedControl.Item
            value="entire-project"
            onClick={() => setOpen(true)}
            aria-haspopup="listbox"
            aria-expanded={open}
          >
            <span className="inline-flex items-center gap-1.5">
              {rightLabel}
              <CaretDownIcon
                size={10}
                weight="bold"
                className="text-muted-foreground"
              />
            </span>
          </SegmentedControl.Item>
        </SegmentedControl.Root>
      </div>
      <ComboboxContent
        anchor={anchorRef}
        align="end"
        side="bottom"
        sideOffset={6}
        // The segmented toggle already shows which scope is active, so the
        // Combobox's built-in right-edge check on the selected row is just
        // visual noise — hide it and reclaim the reserved padding.
        className="min-w-[220px] [&_[data-slot=combobox-item]>span.absolute]:hidden [&_[data-slot=combobox-item][aria-selected=true]]:pe-2!"
      >
        <ComboboxInput
          placeholder="Search people…"
          showTrigger={false}
          autoFocus
        />
        <ComboboxEmpty>No matching people.</ComboboxEmpty>
        <ComboboxList className="max-h-[min(16rem,calc(var(--available-height,16rem)-5rem))]">
          {(itemValue: string) => {
            if (itemValue === PICKER_ENTIRE_PROJECT_VALUE) {
              return (
                <ComboboxItem
                  key={PICKER_ENTIRE_PROJECT_VALUE}
                  value={PICKER_ENTIRE_PROJECT_VALUE}
                  title="Entire project everyone team"
                  className="gap-2"
                >
                  <span
                    className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-(--gray-8) border-dashed text-gray-10"
                    aria-hidden
                  >
                    <AsteriskSimpleIcon size={12} weight="bold" />
                  </span>
                  <span className="min-w-0 flex-1 truncate text-left">
                    Entire project
                  </span>
                </ComboboxItem>
              );
            }
            const teammateUuid = parseTeammateInboxScope(
              itemValue as InboxScope,
            );
            if (!teammateUuid) return null;
            const teammate = teammateOptions.find(
              (t) => t.uuid === teammateUuid,
            );
            if (!teammate) return null;
            const displayName = getSuggestedReviewerDisplayName(teammate);
            const searchText = [
              displayName,
              teammate.name,
              teammate.email,
              teammate.github_login,
            ]
              .filter(Boolean)
              .join(" ");
            return (
              <ComboboxItem
                key={itemValue}
                value={itemValue}
                title={searchText}
                className="gap-2"
              >
                <ReviewerAvatar
                  seed={teammate.uuid}
                  name={teammate.name}
                  email={teammate.email}
                />
                <span className="min-w-0 flex-1 truncate text-left">
                  {displayName}
                </span>
              </ComboboxItem>
            );
          }}
        </ComboboxList>
      </ComboboxContent>
    </Combobox>
  );
}
