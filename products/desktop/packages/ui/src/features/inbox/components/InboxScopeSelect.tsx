import {
  AsteriskSimpleIcon,
  CaretDownIcon,
  UserIcon,
} from "@phosphor-icons/react";
import {
  INBOX_SCOPE_ENTIRE_PROJECT,
  INBOX_SCOPE_FOR_YOU,
  type InboxScope,
  isTeammateInboxScope,
  parseTeammateInboxScope,
  teammateInboxScope,
} from "@posthog/core/inbox/reportMembership";
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
import { ReviewerAvatar } from "@posthog/ui/features/inbox/components/ReviewerAvatar";
import { getInboxScopeOptionLabel } from "@posthog/ui/features/inbox/filterOptions";
import { useInboxScopeOptions } from "@posthog/ui/features/inbox/hooks/useInboxScopeOptions";
import { useInboxReviewerScopeStore } from "@posthog/ui/features/inbox/stores/inboxReviewerScopeStore";
import { useMemo, useRef, useState } from "react";

const PICKER_ENTIRE_PROJECT_VALUE = "__entire-project__";

export function InboxScopeSelect() {
  const scope = useInboxReviewerScopeStore((s) => s.scope);
  const setScope = useInboxReviewerScopeStore((s) => s.setScope);
  const anchorRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const { people } = useInboxScopeOptions();

  const selectedPerson = useMemo(() => {
    const personUuid = parseTeammateInboxScope(scope);
    if (!personUuid) return null;
    return people.find((option) => option.uuid === personUuid) ?? null;
  }, [scope, people]);

  const rightLabel = selectedPerson
    ? getInboxScopeOptionLabel(selectedPerson)
    : "Entire project";

  const pickerItems = useMemo(() => {
    const items: string[] = [INBOX_SCOPE_FOR_YOU, PICKER_ENTIRE_PROJECT_VALUE];
    for (const person of people) {
      items.push(teammateInboxScope(person.uuid));
    }
    return items;
  }, [people]);

  const pickerValue: string =
    scope === INBOX_SCOPE_FOR_YOU
      ? INBOX_SCOPE_FOR_YOU
      : isTeammateInboxScope(scope)
        ? scope
        : PICKER_ENTIRE_PROJECT_VALUE;
  const triggerLabel = scope === INBOX_SCOPE_FOR_YOU ? "For you" : rightLabel;

  const handlePickerValueChange = (value: unknown) => {
    if (typeof value !== "string") return;
    if (value === INBOX_SCOPE_FOR_YOU) {
      setScope(INBOX_SCOPE_FOR_YOU);
    } else if (value === PICKER_ENTIRE_PROJECT_VALUE) {
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
      <ComboboxTrigger
        render={
          <Button
            ref={anchorRef}
            type="button"
            variant="outline"
            size="default"
            aria-label={`Self-driving scope: ${triggerLabel}`}
            className="gap-1.5"
          >
            {triggerLabel}
            <CaretDownIcon size={11} weight="bold" className="text-gray-10" />
          </Button>
        }
      />
      <ComboboxContent
        anchor={anchorRef}
        align="end"
        side="bottom"
        sideOffset={6}
        className="min-w-[220px]"
      >
        <ComboboxInput
          placeholder="Search people…"
          showTrigger={false}
          autoFocus
        />
        <ComboboxEmpty>No matching people.</ComboboxEmpty>
        <ComboboxList className="max-h-[min(16rem,calc(var(--available-height,16rem)-5rem))]">
          {(itemValue: string) => {
            if (itemValue === INBOX_SCOPE_FOR_YOU) {
              return (
                <ComboboxItem
                  key={INBOX_SCOPE_FOR_YOU}
                  value={INBOX_SCOPE_FOR_YOU}
                  title="For you"
                  className="gap-2"
                >
                  <span className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-(--gray-7) text-gray-11">
                    <UserIcon size={12} />
                  </span>
                  <span className="min-w-0 flex-1 truncate text-left">
                    For you
                  </span>
                </ComboboxItem>
              );
            }
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
            const personUuid = parseTeammateInboxScope(itemValue as InboxScope);
            if (!personUuid) return null;
            const person = people.find((p) => p.uuid === personUuid);
            if (!person) return null;
            const displayName = getInboxScopeOptionLabel(person);
            const searchText = [
              displayName,
              person.name,
              person.email,
              person.github_login,
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
                  seed={person.uuid}
                  name={person.name}
                  email={person.email}
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
