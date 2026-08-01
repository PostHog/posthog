import {
  CaretDownIcon,
  MagnifyingGlassIcon,
  UserIcon,
} from "@phosphor-icons/react";
import {
  Combobox,
  ComboboxChip,
  ComboboxChips,
  ComboboxChipsInput,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
  ComboboxTrigger,
  ComboboxValue,
  Button as QuillButton,
} from "@posthog/quill";
import type {
  AgentSessionState,
  AgentUserWithConnections,
} from "@posthog/shared/agent-platform-types";
import { Button } from "@posthog/ui/primitives/Button";
import { useDebouncedValue } from "@posthog/ui/primitives/hooks/useDebouncedValue";
import { Flex, Text } from "@radix-ui/themes";
import { useMemo, useRef, useState } from "react";
import { useAgentApplicationSessions } from "../hooks/useAgentApplicationSessions";
import { useAgentUsers } from "../hooks/useAgentUsers";
import { userDisplayName } from "../utils/format";
import { AgentDetailEmptyState, AgentDetailLayout } from "./AgentDetailLayout";
import { AgentSessionRow } from "./AgentSessionRow";
import { RefreshIndicator } from "./RefreshIndicator";

const STATE_OPTIONS: AgentSessionState[] = [
  "running",
  "completed",
  "failed",
  "cancelled",
  "queued",
];

function stateLabel(state: AgentSessionState): string {
  return state.charAt(0).toUpperCase() + state.slice(1);
}

const ALL_USERS = "all";

function userLabel(u: AgentUserWithConnections): string {
  return `${u.principal_kind}: ${userDisplayName(u) ?? u.principal_id}`;
}

const PAGE = 25;

/** Per-agent Sessions pane: searchable, state + user filtered, paged history. */
export function AgentSessionsPane({ idOrSlug }: { idOrSlug: string }) {
  const [queryInput, setQueryInput] = useState("");
  const { debounced: search } = useDebouncedValue(queryInput.trim(), 300);
  const [states, setStates] = useState<AgentSessionState[]>([]);
  const [userId, setUserId] = useState<string>(ALL_USERS);
  const [limit, setLimit] = useState(PAGE);

  const changeQuery = (next: string) => {
    setQueryInput(next);
    setLimit(PAGE);
  };
  const changeStates = (next: AgentSessionState[]) => {
    setStates(next);
    setLimit(PAGE);
  };
  const changeUser = (next: string) => {
    setUserId(next);
    setLimit(PAGE);
  };

  const { data, isLoading, isError, isFetching, dataUpdatedAt, refetch } =
    useAgentApplicationSessions(idOrSlug, {
      limit,
      state: states.length > 0 ? states : undefined,
      agent_user_id: userId === ALL_USERS ? undefined : userId,
      search: search || undefined,
    });

  const { data: usersData } = useAgentUsers(idOrSlug);
  const users = usersData?.results ?? [];

  const sessions = data?.results ?? [];
  const total = data?.count ?? sessions.length;
  const hasMore = sessions.length < total;
  const hasFilters =
    states.length > 0 || userId !== ALL_USERS || search.length > 0;

  return (
    <AgentDetailLayout idOrSlug={idOrSlug} activeTab="sessions">
      <Flex direction="column" gap="4">
        <Flex align="center" justify="between" gap="3" wrap="wrap">
          <div className="relative min-w-0 flex-1 sm:max-w-xs">
            <MagnifyingGlassIcon
              size={13}
              className="-translate-y-1/2 pointer-events-none absolute top-1/2 left-2.5 text-gray-10"
            />
            <input
              type="search"
              value={queryInput}
              onChange={(e) => changeQuery(e.currentTarget.value)}
              placeholder="Search conversations…"
              aria-label="Search sessions"
              className="h-8 w-full rounded-(--radius-2) border border-border bg-(--color-panel-solid) pr-2 pl-8 text-[12.5px]"
            />
          </div>
          <Flex align="center" gap="2" wrap="wrap" className="shrink-0">
            <SessionStateFilter value={states} onChange={changeStates} />
            {users.length > 0 ? (
              <SessionUserFilter
                users={users}
                value={userId}
                onChange={changeUser}
              />
            ) : null}
            <RefreshIndicator
              updatedAt={dataUpdatedAt}
              isFetching={isFetching}
              onRefresh={() => void refetch()}
            />
          </Flex>
        </Flex>

        {isLoading ? (
          <Flex direction="column" gap="2">
            {[0, 1, 2, 3].map((i) => (
              <div
                key={i}
                className="h-13 animate-pulse rounded-(--radius-2) border border-border bg-(--gray-2)"
              />
            ))}
          </Flex>
        ) : isError ? (
          <AgentDetailEmptyState
            title="Couldn't load sessions"
            description="The agent platform API returned an error."
          />
        ) : sessions.length === 0 ? (
          <AgentDetailEmptyState
            title="No sessions"
            description={
              hasFilters
                ? "No sessions match your search and filters."
                : "This agent hasn't run any sessions yet."
            }
          />
        ) : (
          <Flex direction="column" gap="2">
            {sessions.map((session) => (
              <AgentSessionRow
                key={session.id}
                session={session}
                idOrSlug={idOrSlug}
              />
            ))}
            <Flex align="center" justify="between" className="pt-1">
              <Text className="text-[11px] text-gray-10">
                Showing {sessions.length} of {total}
              </Text>
              {hasMore ? (
                <Button
                  variant="soft"
                  size="1"
                  onClick={() => setLimit((l) => l + PAGE)}
                  loading={isFetching}
                >
                  Load more
                </Button>
              ) : null}
            </Flex>
          </Flex>
        )}
      </Flex>
    </AgentDetailLayout>
  );
}

function SessionStateFilter({
  value,
  onChange,
}: {
  value: AgentSessionState[];
  onChange: (next: AgentSessionState[]) => void;
}) {
  const anchorRef = useRef<HTMLDivElement>(null);
  return (
    <Combobox<AgentSessionState, true>
      multiple
      items={STATE_OPTIONS}
      value={value}
      onValueChange={(next) => onChange(next ?? [])}
      itemToStringLabel={stateLabel}
    >
      <ComboboxChips
        ref={anchorRef}
        className="flex min-h-8 w-52 flex-wrap items-center gap-1 rounded-(--radius-2) border border-border bg-(--color-panel-solid) px-1.5 py-1"
      >
        <ComboboxValue>
          {(selected: AgentSessionState[]) =>
            selected.map((state) => (
              <ComboboxChip key={state} showRemove>
                {stateLabel(state)}
              </ComboboxChip>
            ))
          }
        </ComboboxValue>
        <ComboboxChipsInput
          placeholder={value.length === 0 ? "All states" : ""}
          aria-label="Filter by state"
          className="min-w-12 flex-1 bg-transparent text-[12px] text-gray-12 outline-none placeholder:text-gray-10"
        />
      </ComboboxChips>
      <ComboboxContent anchor={anchorRef} align="start" sideOffset={4}>
        <ComboboxEmpty>No states</ComboboxEmpty>
        <ComboboxList>
          {(state: AgentSessionState) => (
            <ComboboxItem key={state} value={state}>
              {stateLabel(state)}
            </ComboboxItem>
          )}
        </ComboboxList>
      </ComboboxContent>
    </Combobox>
  );
}

function SessionUserFilter({
  users,
  value,
  onChange,
}: {
  users: AgentUserWithConnections[];
  value: string;
  onChange: (next: string) => void;
}) {
  const anchorRef = useRef<HTMLButtonElement>(null);
  const items = useMemo(() => [ALL_USERS, ...users.map((u) => u.id)], [users]);
  const labelById = useMemo(() => {
    const map = new Map<string, string>([[ALL_USERS, "All users"]]);
    for (const u of users) map.set(u.id, userLabel(u));
    return map;
  }, [users]);
  const labelFor = (id: string) => labelById.get(id) ?? id;

  return (
    <Combobox<string, false>
      items={items}
      value={value}
      onValueChange={(next) => onChange(next ?? ALL_USERS)}
      itemToStringLabel={labelFor}
    >
      <ComboboxTrigger
        render={
          <QuillButton
            ref={anchorRef}
            variant="outline"
            size="sm"
            aria-label="Filter by user"
            className="min-w-0 max-w-52"
          >
            <UserIcon size={13} className="shrink-0 text-gray-10" />
            <span className="min-w-0 truncate">{labelFor(value)}</span>
            <CaretDownIcon size={10} className="shrink-0 text-gray-10" />
          </QuillButton>
        }
      />
      <ComboboxContent
        anchor={anchorRef}
        align="end"
        sideOffset={6}
        className="min-w-55"
      >
        <ComboboxInput placeholder="Search users…" />
        <ComboboxEmpty>No users found.</ComboboxEmpty>
        <ComboboxList>
          {(id: string) => (
            <ComboboxItem key={id} value={id} title={labelFor(id)}>
              {labelFor(id)}
            </ComboboxItem>
          )}
        </ComboboxList>
      </ComboboxContent>
    </Combobox>
  );
}
