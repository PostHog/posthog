import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
} from "@posthog/quill";
import type { UserBasic } from "@posthog/shared/domain-types";
import { UserAvatar } from "@posthog/ui/features/auth/UserAvatar";
import { useOrgMembers } from "@posthog/ui/features/canvas/hooks/useOrgMembers";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import { useMemo } from "react";

export function MemberSearch({
  excludeIds,
  onPick,
  disabled,
  placeholder = "Search people…",
}: {
  excludeIds: number[];
  onPick: (id: number) => void;
  disabled?: boolean;
  placeholder?: string;
}) {
  const { members, isLoading } = useOrgMembers();
  const byId = useMemo(() => {
    const map = new Map<number, UserBasic>();
    for (const member of members) map.set(member.id, member);
    return map;
  }, [members]);
  const excluded = useMemo(() => new Set(excludeIds), [excludeIds]);
  const addableIds = useMemo(
    () =>
      members
        .filter((member) => !excluded.has(member.id))
        .map((member) => String(member.id)),
    [members, excluded],
  );

  return (
    <Combobox<string>
      items={addableIds}
      value={null}
      onValueChange={(value) => value && onPick(Number(value))}
      itemToStringLabel={(id) => {
        const member = byId.get(Number(id));
        return member ? userDisplayName(member) : "";
      }}
      filter={(id, query) => {
        const needle = query.trim().toLowerCase();
        if (!needle) return true;
        const member = byId.get(Number(id));
        if (!member) return false;
        return (
          userDisplayName(member).toLowerCase().includes(needle) ||
          (member.email ?? "").toLowerCase().includes(needle)
        );
      }}
      autoHighlight
      disabled={disabled}
    >
      <ComboboxInput
        placeholder={placeholder}
        disabled={disabled}
        className="w-full"
      />
      <ComboboxContent className="w-[var(--anchor-width)] min-w-[240px]">
        <ComboboxEmpty>
          {isLoading ? "Loading people…" : "No people to add."}
        </ComboboxEmpty>
        <ComboboxList className="max-h-[min(18rem,calc(var(--available-height,18rem)-2rem))]">
          {(itemId: string) => {
            const member = byId.get(Number(itemId));
            if (!member) return null;
            return (
              <ComboboxItem key={itemId} value={itemId}>
                <UserAvatar user={member} size="xs" className="shrink-0" />
                <span className="min-w-0 truncate">
                  {userDisplayName(member)}
                </span>
                <span className="ml-auto shrink-0 truncate text-muted-foreground text-xs">
                  {member.email}
                </span>
              </ComboboxItem>
            );
          }}
        </ComboboxList>
      </ComboboxContent>
    </Combobox>
  );
}
