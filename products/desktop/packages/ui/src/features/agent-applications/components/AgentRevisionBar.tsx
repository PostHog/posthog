import { CaretDownIcon } from "@phosphor-icons/react";
import { formatRelativeTimeShort } from "@posthog/shared";
import type {
  AgentApplication,
  AgentRevision,
  AgentRevisionState,
} from "@posthog/shared/agent-platform-types";
import { Badge } from "@posthog/ui/primitives/Badge";
import { Button } from "@posthog/ui/primitives/Button";
import { AlertDialog, Flex, Popover, Text } from "@radix-ui/themes";
import { useNavigate } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useAgentRevisionLifecycle } from "../hooks/useAgentRevisionLifecycle";
import { useCreateAgentDraftFromRevision } from "../hooks/useCreateAgentDraftFromRevision";
import { revisionStateColor } from "../utils/format";
import { AgentBundleImportDialog } from "./AgentBundleImportDialog";

type LifecycleAction = "freeze" | "promote" | "archive";

/** Last segment, first 8 chars — a stable short handle for a revision UUID. */
function shortId(id: string): string {
  return id.split("-").at(-1)?.slice(0, 8) ?? id.slice(0, 8);
}

function stateLabel(rev: AgentRevision, isLive: boolean): string {
  return isLive ? "live" : rev.state;
}

const STATE_FILTERS: AgentRevisionState[] = [
  "live",
  "ready",
  "draft",
  "archived",
];

function lifecycleActionsFor(
  state: AgentRevisionState,
  isLive: boolean,
  hasLiveRevision: boolean,
): { label: string; action: LifecycleAction; destructive?: boolean }[] {
  const out: {
    label: string;
    action: LifecycleAction;
    destructive?: boolean;
  }[] = [];
  if (state === "draft") out.push({ label: "Freeze", action: "freeze" });
  if (state === "ready")
    out.push({ label: "Promote to live", action: "promote" });
  if (state !== "archived" && !(isLive && hasLiveRevision))
    out.push({ label: "Archive", action: "archive", destructive: true });
  return out;
}

function dialogCopy(
  action: LifecycleAction,
  revision: AgentRevision,
  agent: AgentApplication,
): { title: string; description: string; confirmLabel: string } {
  const id = shortId(revision.id);
  if (action === "freeze") {
    return {
      title: `Freeze revision ${id}`,
      description:
        "Stamps the bundle and locks the spec — the revision moves from draft to ready and becomes immutable. Required before promoting to live.",
      confirmLabel: "Freeze",
    };
  }
  if (action === "promote") {
    const replacing =
      agent.live_revision && agent.live_revision !== revision.id;
    return {
      title: `Promote ${id} to live`,
      description: replacing
        ? `The current live revision will be archived and traffic switches to ${id} immediately.`
        : `This becomes the live revision for ${agent.name}. Triggers start serving from it immediately.`,
      confirmLabel: "Promote to live",
    };
  }
  return {
    title: `Archive revision ${id}`,
    description:
      revision.id === agent.live_revision
        ? "This is the live revision — archiving it leaves the agent with no deployable version until another is promoted."
        : "This revision will be hidden from the default list and can no longer be promoted.",
    confirmLabel: "Archive",
  };
}

/**
 * The bar above the config explorer: a revision picker (state-filtered list)
 * plus the operational lifecycle actions for the selected revision
 * (freeze / promote / archive), each behind a confirm. Authoring a revision's
 * contents is the agent builder's job — this only moves a revision through its
 * lifecycle.
 */
export function AgentRevisionBar({
  idOrSlug,
  agent,
  revisions,
  selectedRevisionId,
  onSelectRevision,
}: {
  idOrSlug: string;
  agent: AgentApplication;
  revisions: AgentRevision[];
  selectedRevisionId: string | null;
  onSelectRevision: (id: string) => void;
}) {
  const lifecycle = useAgentRevisionLifecycle(idOrSlug);
  const cloneToDraft = useCreateAgentDraftFromRevision(idOrSlug, agent.id);
  const navigate = useNavigate();
  const [pickerOpen, setPickerOpen] = useState(false);
  const [filters, setFilters] = useState<Set<AgentRevisionState>>(
    () => new Set<AgentRevisionState>(["live", "ready", "draft"]),
  );
  const [pending, setPending] = useState<{
    action: LifecycleAction;
    revision: AgentRevision;
  } | null>(null);
  const [importOpen, setImportOpen] = useState(false);

  const selected =
    revisions.find((r) => r.id === selectedRevisionId) ?? revisions[0] ?? null;
  const isLive = !!selected && selected.id === agent.live_revision;
  const actions = selected
    ? lifecycleActionsFor(selected.state, isLive, !!agent.live_revision)
    : [];
  // Skill ids already declared on the selected revision — drives the
  // new / update badge in the bulk-import preview.
  const existingSkillIds = useMemo<string[]>(() => {
    const skills = selected?.spec?.skills;
    if (!Array.isArray(skills)) return [];
    return skills.flatMap((s) => {
      const id =
        s && typeof s === "object" && "id" in s
          ? (s as { id?: unknown }).id
          : undefined;
      return typeof id === "string" ? [id] : [];
    });
  }, [selected]);

  const visible = useMemo(
    () =>
      [...revisions]
        .sort(
          (a, b) =>
            new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
        )
        .filter((r) =>
          filters.has(r.id === agent.live_revision ? "live" : r.state),
        ),
    [revisions, filters, agent.live_revision],
  );

  function toggleFilter(f: AgentRevisionState) {
    setFilters((prev) => {
      const next = new Set(prev);
      if (next.has(f)) next.delete(f);
      else next.add(f);
      return next;
    });
  }

  if (!selected) return null;
  const copy = pending
    ? dialogCopy(pending.action, pending.revision, agent)
    : null;

  return (
    <Flex
      align="center"
      justify="between"
      gap="3"
      className="shrink-0 border-(--gray-5) border-b px-4 py-2"
    >
      <Popover.Root open={pickerOpen} onOpenChange={setPickerOpen}>
        <Popover.Trigger>
          <button
            type="button"
            className="flex items-center gap-2 rounded-(--radius-2) border border-border bg-(--color-panel-solid) px-2.5 py-1.5 text-left hover:border-(--gray-7)"
          >
            <Badge color={revisionStateColor(selected.state)}>
              {stateLabel(selected, isLive)}
            </Badge>
            <code className="text-[12px] text-gray-12 [font-family:var(--font-mono)]">
              {shortId(selected.id)}
            </code>
            <Text className="text-[11px] text-gray-10">
              {formatRelativeTimeShort(selected.updated_at)}
            </Text>
            <CaretDownIcon size={12} className="text-gray-10" />
          </button>
        </Popover.Trigger>
        <Popover.Content size="1" width="320px" className="p-0">
          <div className="border-(--gray-5) border-b px-2 py-2">
            <Flex gap="1" wrap="wrap">
              {STATE_FILTERS.map((f) => {
                const active = filters.has(f);
                return (
                  <button
                    key={f}
                    type="button"
                    onClick={() => toggleFilter(f)}
                    aria-pressed={active}
                    className={`rounded-(--radius-2) border px-1.5 py-[3px] text-[10.5px] uppercase leading-none tracking-wide ${
                      active
                        ? "border-(--accent-7) bg-(--accent-3) text-gray-12"
                        : "border-border text-gray-10 hover:border-(--gray-7)"
                    }`}
                  >
                    {f}
                  </button>
                );
              })}
            </Flex>
          </div>
          <ul className="max-h-72 divide-y divide-(--gray-4) overflow-auto">
            {visible.length === 0 ? (
              <li className="px-3 py-3 text-[12px] text-gray-10">
                No matching revisions.
              </li>
            ) : (
              visible.map((r) => {
                const live = r.id === agent.live_revision;
                return (
                  <li key={r.id}>
                    <button
                      type="button"
                      onClick={() => {
                        onSelectRevision(r.id);
                        setPickerOpen(false);
                      }}
                      aria-current={r.id === selected.id ? "true" : undefined}
                      className={`flex w-full items-center gap-2 px-3 py-2 text-left ${
                        r.id === selected.id
                          ? "bg-(--accent-3)"
                          : "hover:bg-(--gray-3)"
                      }`}
                    >
                      <Badge color={revisionStateColor(r.state)}>
                        {stateLabel(r, live)}
                      </Badge>
                      <div className="min-w-0 flex-1">
                        <code className="text-[11.5px] text-gray-12 [font-family:var(--font-mono)]">
                          {shortId(r.id)}
                        </code>
                        <div className="text-[10.5px] text-gray-10">
                          {formatRelativeTimeShort(r.updated_at)}
                          {r.created_by?.first_name
                            ? ` · ${r.created_by.first_name}`
                            : ""}
                        </div>
                      </div>
                    </button>
                  </li>
                );
              })
            )}
          </ul>
        </Popover.Content>
      </Popover.Root>

      <Flex gap="2">
        {/*
         * Test — routes this not-yet-promoted revision through the ingress
         * with a short-lived JWT (the chat tab mints + attaches it via
         * useAgentChat). Side effects run for real; the revision serving the
         * request is the only difference from a live chat. Live uses the
         * default Chat tab; archived can't be exercised.
         */}
        {selected.state !== "live" &&
        selected.state !== "archived" &&
        !isLive ? (
          <Button
            size="1"
            variant="soft"
            color="gray"
            onClick={() =>
              navigate({
                to: "/code/agents/applications/$idOrSlug/chat",
                params: { idOrSlug },
                search: { revision: selected.id },
              })
            }
          >
            {selected.state === "draft" ? "Test draft" : "Test"}
          </Button>
        ) : null}
        {/*
         * Clone to draft — fork this revision into a fresh editable draft (the
         * exit when a ready/live/archived bundle is immutable but you want to
         * keep iterating). Pre-selects the new draft.
         */}
        {selected.state !== "draft" ? (
          <Button
            size="1"
            variant="soft"
            color="gray"
            loading={cloneToDraft.isPending}
            disabled={!agent.id}
            onClick={() =>
              cloneToDraft.mutate(
                { sourceRevisionId: selected.id },
                { onSuccess: (rev) => onSelectRevision(rev.id) },
              )
            }
          >
            Clone to draft
          </Button>
        ) : null}
        {/*
         * Paste markdown bundle — bulk import for the multi-file migration
         * case (e.g. porting an existing growth-review agent in one paste).
         * Per-file edit lives in the configuration pane; this is the hatch
         * when there are several files to seed at once.
         */}
        {selected.state === "draft" ? (
          <Button
            size="1"
            variant="soft"
            color="gray"
            onClick={() => setImportOpen(true)}
          >
            Paste markdown bundle…
          </Button>
        ) : null}
        {actions.map((a) => (
          <Button
            key={a.action}
            size="1"
            variant="soft"
            color={a.destructive ? "red" : "gray"}
            onClick={() => setPending({ action: a.action, revision: selected })}
          >
            {a.label}
          </Button>
        ))}
      </Flex>

      {selected.state === "draft" ? (
        <AgentBundleImportDialog
          open={importOpen}
          onOpenChange={setImportOpen}
          idOrSlug={idOrSlug}
          revisionId={selected.id}
          existingSkillIds={existingSkillIds}
        />
      ) : null}

      <AlertDialog.Root
        open={!!pending}
        onOpenChange={(open) => {
          if (!open && !lifecycle.isPending) setPending(null);
        }}
      >
        <AlertDialog.Content maxWidth="440px" size="2">
          {copy && pending ? (
            <>
              <AlertDialog.Title className="text-base">
                {copy.title}
              </AlertDialog.Title>
              <AlertDialog.Description size="2" className="text-gray-11">
                {copy.description}
              </AlertDialog.Description>
              {lifecycle.isError ? (
                <Text className="mt-2 block text-(--red-11) text-[12px]">
                  {lifecycle.error?.message ?? "Action failed"}
                </Text>
              ) : null}
              <Flex gap="3" mt="4" justify="end">
                <Button
                  variant="soft"
                  color="gray"
                  disabled={lifecycle.isPending}
                  onClick={() => setPending(null)}
                >
                  Cancel
                </Button>
                <Button
                  color={pending.action === "archive" ? "red" : "green"}
                  loading={lifecycle.isPending}
                  onClick={() =>
                    lifecycle.mutate(
                      {
                        revisionId: pending.revision.id,
                        action: pending.action,
                      },
                      { onSuccess: () => setPending(null) },
                    )
                  }
                >
                  {copy.confirmLabel}
                </Button>
              </Flex>
            </>
          ) : null}
        </AlertDialog.Content>
      </AlertDialog.Root>
    </Flex>
  );
}
