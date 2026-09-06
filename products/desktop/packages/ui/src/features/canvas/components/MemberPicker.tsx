import { XIcon } from "@phosphor-icons/react";
import {
  Button,
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

/**
 * Pick project members for a private space: a search box that adds a person, and
 * a list of the chosen ones with a remove control. `lockedId` marks a member who
 * cannot be removed (the space creator), shown with a "Creator" tag instead.
 */
export function MemberPicker({
  selectedIds,
  onChange,
  disabled,
  lockedId = null,
}: {
  selectedIds: number[];
  onChange: (ids: number[]) => void;
  disabled?: boolean;
  lockedId?: number | null;
}) {
  const { members: orgMembers, isLoading } = useOrgMembers();

  const byId = useMemo(() => {
    const map = new Map<number, UserBasic>();
    for (const member of orgMembers) map.set(member.id, member);
    return map;
  }, [orgMembers]);

  const chosen = useMemo(() => new Set(selectedIds), [selectedIds]);
  const addableIds = useMemo(
    () =>
      orgMembers
        .filter((member) => !chosen.has(member.id))
        .map((member) => String(member.id)),
    [orgMembers, chosen],
  );

  const selectedMembers = useMemo(
    () =>
      selectedIds
        .map((id) => byId.get(id))
        .filter((user): user is UserBasic => !!user),
    [selectedIds, byId],
  );

  const addMember = (id: number) => {
    if (!chosen.has(id)) onChange([...selectedIds, id]);
  };
  const removeMember = (id: number) => {
    onChange(selectedIds.filter((memberId) => memberId !== id));
  };

  return (
    <div className="flex flex-col gap-2">
      <Combobox<string>
        items={addableIds}
        value={null}
        onValueChange={(value) => value && addMember(Number(value))}
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
          placeholder="Search people…"
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
      <div className="flex flex-col gap-1">
        {selectedMembers.map((member) => (
          <div
            key={member.id}
            className="flex items-center gap-2 rounded-(--radius-2) px-1 py-1"
          >
            <UserAvatar user={member} size="xs" className="shrink-0" />
            <span className="min-w-0 truncate text-sm">
              {userDisplayName(member)}
            </span>
            <span className="ml-auto min-w-0 shrink truncate text-muted-foreground text-xs">
              {member.id === lockedId ? "Creator" : member.email}
            </span>
            {member.id === lockedId ? null : (
              <Button
                variant="outline"
                size="icon-sm"
                aria-label={`Remove ${userDisplayName(member)}`}
                disabled={disabled}
                onClick={() => removeMember(member.id)}
              >
                <XIcon size={14} />
              </Button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
