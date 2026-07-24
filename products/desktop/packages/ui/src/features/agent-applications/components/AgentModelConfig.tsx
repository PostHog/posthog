import { PointerSensor } from "@dnd-kit/dom";
import { type DragDropEvents, DragDropProvider } from "@dnd-kit/react";
import { useSortable } from "@dnd-kit/react/sortable";
import {
  BrainIcon,
  CaretDownIcon,
  GaugeIcon,
  MagnifyingGlassIcon,
  ScalesIcon,
  SlidersHorizontalIcon,
} from "@phosphor-icons/react";
import type {
  AgentModelEntry,
  AgentModelLevel,
  AgentModelOptimizeFor,
  AgentModelPolicy,
  AgentReasoningEffort,
  AgentRevisionState,
  AgentSpec,
  ModelCatalogEntry,
} from "@posthog/shared/agent-platform-types";
import { Badge } from "@posthog/ui/primitives/Badge";
import { Button } from "@posthog/ui/primitives/Button";
import { Flex, Popover, Text } from "@radix-ui/themes";
import { type ReactNode, type RefCallback, useMemo, useState } from "react";
import { useApplyAgentSpec } from "../hooks/useApplyAgentSpec";
import { useModelCatalog } from "../hooks/useModelCatalog";

/**
 * The rich model section: an interactive policy editor (mode + level +
 * reasoning), a preview of what an `auto` level resolves to, and a searchable
 * browser of every served model with its cost profile. Save goes through
 * `useApplyAgentSpec`, which PATCHes a draft in place or branches a fresh
 * draft from a non-draft revision first.
 */
export function AgentModelConfig({
  spec,
  idOrSlug,
  applicationId,
  revisionId,
  revisionState,
  onSelectRevision,
}: {
  spec: AgentSpec;
  idOrSlug: string;
  applicationId?: string;
  revisionId: string;
  revisionState?: AgentRevisionState;
  onSelectRevision?: (revisionId: string) => void;
}) {
  const { catalog } = useModelCatalog();
  const apply = useApplyAgentSpec(idOrSlug, applicationId);
  const initial = spec.models;

  const [mode, setMode] = useState<"auto" | "manual">(initial?.mode ?? "auto");
  const [level, setLevel] = useState<AgentModelLevel>(
    initial?.mode === "auto" ? (initial.level ?? "medium") : "medium",
  );
  const [reasoning, setReasoning] = useState<AgentReasoningEffort | undefined>(
    initial?.mode === "auto" ? initial.reasoning : spec.reasoning,
  );
  const [manual, setManual] = useState<AgentModelEntry[]>(
    initial?.mode === "manual" ? initial.models : [],
  );
  const [optimizeFor, setOptimizeFor] = useState<AgentModelOptimizeFor>(
    initial?.optimize_for ?? "cost",
  );

  const policy: AgentModelPolicy =
    mode === "auto"
      ? {
          mode: "auto",
          level,
          optimize_for: optimizeFor,
          ...(reasoning ? { reasoning } : {}),
        }
      : { mode: "manual", models: manual, optimize_for: optimizeFor };

  const dirty =
    stableStringify(policy) !==
    stableStringify(
      initial ?? { mode: "auto", level: "medium", optimize_for: "cost" },
    );
  const willBranch = revisionState !== "draft";

  const byId = useMemo(
    () => new Map(catalog.models.map((m) => [m.model, m])),
    [catalog.models],
  );

  function reset() {
    setMode(initial?.mode ?? "auto");
    setLevel(initial?.mode === "auto" ? (initial.level ?? "medium") : "medium");
    setReasoning(initial?.mode === "auto" ? initial.reasoning : spec.reasoning);
    setManual(initial?.mode === "manual" ? initial.models : []);
    setOptimizeFor(initial?.optimize_for ?? "cost");
  }

  function changeMode(next: "auto" | "manual") {
    // Switching to manual with an empty list seeds it from the level you were
    // on, so you start from auto's choices and edit rather than a blank slate.
    if (next === "manual" && manual.length === 0) {
      setManual((catalog.levels[level] ?? []).map((model) => ({ model })));
    }
    setMode(next);
  }

  function save() {
    apply.mutate(
      {
        revision: { id: revisionId, state: revisionState ?? "draft" },
        spec: { ...spec, models: policy },
      },
      { onSuccess: (rev) => onSelectRevision?.(rev.id) },
    );
  }

  return (
    <Flex direction="column" gap="4">
      {dirty ? (
        <Flex
          direction="column"
          gap="1.5"
          className="rounded-(--radius-2) border border-(--amber-6) bg-(--amber-2) px-3 py-2"
        >
          <Flex align="center" justify="between" gap="2">
            <Text className="text-[12px] text-amber-11">
              {willBranch
                ? "Unsaved changes — saving branches a new draft."
                : "Unsaved changes."}
            </Text>
            <Flex gap="2" className="shrink-0">
              <Button
                size="1"
                variant="soft"
                color="gray"
                disabled={apply.isPending}
                onClick={reset}
              >
                Reset
              </Button>
              <Button size="1" loading={apply.isPending} onClick={save}>
                {willBranch ? "Save to new draft" : "Save"}
              </Button>
            </Flex>
          </Flex>
          {apply.isError ? (
            <Text className="text-(--red-11) text-[11px]">
              {apply.error?.message ?? "Save failed"}
            </Text>
          ) : null}
        </Flex>
      ) : null}

      <Flex direction="column" gap="3">
        <Select
          label="mode"
          icon={<SlidersHorizontalIcon size={14} />}
          value={mode}
          onChange={(v) => changeMode(v as "auto" | "manual")}
          options={MODE_OPTIONS}
        />

        <Select
          label="optimize for"
          icon={<ScalesIcon size={14} />}
          value={optimizeFor}
          onChange={(v) => setOptimizeFor(v as AgentModelOptimizeFor)}
          options={OPTIMIZE_OPTIONS}
        />

        {mode === "auto" ? (
          <>
            <Select
              label="level"
              icon={<GaugeIcon size={14} />}
              value={level}
              onChange={(v) => setLevel(v as AgentModelLevel)}
              options={LEVEL_OPTIONS}
            />
            <Select
              label="reasoning"
              icon={<BrainIcon size={14} />}
              value={reasoning ?? "default"}
              onChange={(v) =>
                setReasoning(
                  v === "default" ? undefined : (v as AgentReasoningEffort),
                )
              }
              options={REASONING_OPTIONS}
            />
          </>
        ) : null}
      </Flex>

      {mode === "auto" ? (
        <AutoLevelPreview
          level={level}
          ids={catalog.levels[level]}
          byId={byId}
        />
      ) : (
        <ManualEditor models={manual} byId={byId} onChange={setManual} />
      )}

      <Subhead>browse all models · {catalog.models.length}</Subhead>
      <ModelBrowser
        models={catalog.models}
        canAdd={mode === "manual"}
        selected={mode === "manual" ? manual.map((m) => m.model) : []}
        onAdd={(id) =>
          setManual((prev) =>
            prev.some((m) => m.model === id) ? prev : [...prev, { model: id }],
          )
        }
      />
    </Flex>
  );
}

const MODE_OPTIONS = [
  {
    value: "auto",
    title: "Auto",
    description: "Platform-managed list, resolved across providers at runtime.",
  },
  {
    value: "manual",
    title: "Manual",
    description: "Explicit, author-ordered fallback list you pin yourself.",
  },
] as const;

const OPTIMIZE_OPTIONS = [
  {
    value: "cost",
    title: "Cost",
    description:
      "Pin the first working model for the whole session — keeps the prompt cache warm, no mid-session failover.",
  },
  {
    value: "availability",
    title: "Availability",
    description:
      "Fail over to the next model if the session's model goes down — survives outages, but re-reads context cold.",
  },
] as const;

const LEVEL_OPTIONS = [
  {
    value: "low",
    title: "Low",
    description: "Cheapest — short, formulaic, no-reasoning jobs.",
  },
  {
    value: "medium",
    title: "Medium",
    description: "Balanced default — multi-step but bounded work.",
  },
  {
    value: "high",
    title: "High",
    description: "Top-tier — long, branching, reasoning-heavy work.",
  },
] as const;

const REASONING_OPTIONS = [
  {
    value: "default",
    title: "Default",
    description: "Provider / spec default — no explicit budget.",
  },
  {
    value: "minimal",
    title: "Minimal",
    description: "No deliberation — cheapest, fastest.",
  },
  { value: "low", title: "Low", description: "Light deliberation." },
  { value: "medium", title: "Medium", description: "Moderate deliberation." },
  { value: "high", title: "High", description: "Deep deliberation." },
  {
    value: "xhigh",
    title: "Xhigh",
    description: "Maximal — research-grade, ~5–10× the per-turn cost.",
  },
] as const;

const LEVEL_BLURB: Record<AgentModelLevel, string> = {
  low: "Cheapest — short, formulaic, no-reasoning jobs (lookups, FAQ bots).",
  medium: "Balanced default — multi-step but bounded work.",
  high: "Top-tier — long, branching, reasoning-heavy work.",
};

function AutoLevelPreview({
  level,
  ids,
  byId,
}: {
  level: AgentModelLevel;
  ids: string[];
  byId: Map<string, ModelCatalogEntry>;
}) {
  return (
    <Flex direction="column" gap="2">
      <Muted>
        <b className="text-gray-12">auto</b> resolves the level to a maintained,
        priority-ordered, cross-provider list at runtime — the runner tries each
        in order until one answers, so the agent rides upgrades and survives a
        provider outage without a spec change. <b>{level}</b>:{" "}
        {LEVEL_BLURB[level]}
      </Muted>
      <Subhead>{level} resolves to · priority order</Subhead>
      {ids.map((id, i) => {
        const m = byId.get(id);
        return (
          <Flex
            key={id}
            align="center"
            justify="between"
            gap="3"
            className="rounded-(--radius-2) border border-border bg-(--gray-2) px-3 py-2"
          >
            <Flex align="center" gap="2" className="min-w-0">
              <Text className="shrink-0 text-[11px] text-gray-10">
                {i === 0 ? "primary" : `#${i + 1}`}
              </Text>
              <Text className="truncate text-[12.5px] text-gray-12 [font-family:var(--font-mono)]">
                {id}
              </Text>
            </Flex>
            {m ? <CostInline m={m} /> : <Muted>not in catalog</Muted>}
          </Flex>
        );
      })}
    </Flex>
  );
}

function ManualEditor({
  models,
  byId,
  onChange,
}: {
  models: AgentModelEntry[];
  byId: Map<string, ModelCatalogEntry>;
  onChange: (next: AgentModelEntry[]) => void;
}) {
  const ids = models.map((m) => m.model);
  const handleDragOver: DragDropEvents["dragover"] = (event) => {
    const sourceId = event.operation.source?.id;
    const targetId = event.operation.target?.id;
    if (!sourceId || !targetId || sourceId === targetId) return;
    const from = ids.indexOf(String(sourceId));
    const to = ids.indexOf(String(targetId));
    if (from === -1 || to === -1 || from === to) return;
    const next = [...models];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    onChange(next);
  };
  return (
    <Flex direction="column" gap="2">
      <Muted>
        <b className="text-gray-12">manual</b> pins an explicit fallback list
        (primary first). Add models from the browser below; order them
        provider-diverse so a single provider outage degrades instead of
        failing.
      </Muted>
      <Subhead>models · priority order · drag to reorder</Subhead>
      {models.length === 0 ? (
        <Text className="rounded-(--radius-2) border border-(--gray-5) border-dashed px-3 py-3 text-[12px] text-gray-10">
          No models yet — add one from the browser below.
        </Text>
      ) : (
        <DragDropProvider
          onDragOver={handleDragOver}
          sensors={[
            {
              plugin: PointerSensor,
              options: { activationConstraints: { distance: { value: 5 } } },
            },
          ]}
        >
          <Flex direction="column" gap="2">
            {models.map((entry, i) => (
              <SortableModelRow
                key={entry.model}
                id={entry.model}
                index={i}
                entry={entry}
                m={byId.get(entry.model)}
                onRemove={() => onChange(models.filter((_, k) => k !== i))}
              />
            ))}
          </Flex>
        </DragDropProvider>
      )}
    </Flex>
  );
}

function SortableModelRow({
  id,
  index,
  entry,
  m,
  onRemove,
}: {
  id: string;
  index: number;
  entry: AgentModelEntry;
  m?: ModelCatalogEntry;
  onRemove: () => void;
}) {
  const { ref, handleRef, isDragging } = useSortable({
    id,
    index,
    group: "manual-models",
    transition: { duration: 200, easing: "ease" },
  });
  return (
    <div ref={ref} style={{ opacity: isDragging ? 0.5 : 1 }}>
      <Flex
        align="center"
        justify="between"
        gap="3"
        className="rounded-(--radius-2) border border-border bg-(--gray-2) px-3 py-2"
      >
        <Flex align="center" gap="2" className="min-w-0">
          <button
            ref={handleRef as RefCallback<HTMLButtonElement>}
            type="button"
            title="Drag to reorder"
            className="shrink-0 cursor-grab text-[13px] text-gray-9 leading-none hover:text-gray-11"
          >
            ⠿
          </button>
          <Text className="shrink-0 text-[11px] text-gray-10">
            {index === 0 ? "primary" : `#${index + 1}`}
          </Text>
          <Text className="truncate text-[12.5px] text-gray-12 [font-family:var(--font-mono)]">
            {entry.model}
          </Text>
        </Flex>
        <Flex align="center" gap="2" className="shrink-0">
          {m ? <CostInline m={m} /> : null}
          <MiniBtn label="remove" title="Remove" onClick={onRemove} />
        </Flex>
      </Flex>
    </div>
  );
}

type SortKey = "name" | "cheapest" | "priciest";

function ModelBrowser({
  models,
  canAdd,
  selected,
  onAdd,
}: {
  models: ModelCatalogEntry[];
  canAdd: boolean;
  selected: string[];
  onAdd: (id: string) => void;
}) {
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<SortKey>("name");

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const filtered = needle
      ? models.filter(
          (m) =>
            m.model.toLowerCase().includes(needle) ||
            m.provider.toLowerCase().includes(needle),
        )
      : models;
    // Blended per-Mtok cost (input + output), not input alone: reasoning
    // models can have cheap input but dominant output, so input-only mis-ranks
    // exactly the models cost-conscious authors most need to compare.
    const blended = (m: ModelCatalogEntry) => m.input + m.output;
    const sorted = [...filtered];
    if (sort === "name") sorted.sort((a, b) => a.model.localeCompare(b.model));
    if (sort === "cheapest") sorted.sort((a, b) => blended(a) - blended(b));
    if (sort === "priciest") sorted.sort((a, b) => blended(b) - blended(a));
    return sorted;
  }, [models, q, sort]);

  return (
    <Flex direction="column" gap="2">
      <Flex align="center" gap="2" wrap="wrap">
        <div className="relative min-w-0 flex-1">
          <MagnifyingGlassIcon
            size={13}
            className="-translate-y-1/2 pointer-events-none absolute top-1/2 left-2.5 text-gray-10"
          />
          <input
            type="search"
            value={q}
            onChange={(e) => setQ(e.currentTarget.value)}
            placeholder="Search models…"
            aria-label="Search models"
            className="h-8 w-full rounded-(--radius-2) border border-border bg-(--color-panel-solid) pr-2 pl-8 text-[12.5px]"
          />
        </div>
        <Seg
          value={sort}
          onChange={(v) => setSort(v as SortKey)}
          options={[
            { value: "name", label: "Name" },
            { value: "cheapest", label: "Cheapest" },
            { value: "priciest", label: "Priciest" },
          ]}
        />
      </Flex>

      <Flex direction="column" gap="1">
        {rows.map((m) => {
          const added = selected.includes(m.model);
          return (
            <Flex
              key={m.model}
              direction="column"
              gap="1"
              className="rounded-(--radius-2) border border-border bg-(--gray-2) px-3 py-2"
            >
              <Flex align="center" justify="between" gap="2">
                <Text className="truncate text-[12.5px] text-gray-12 [font-family:var(--font-mono)]">
                  {m.model}
                </Text>
                {canAdd ? (
                  <MiniBtn
                    label={added ? "added" : "+ add"}
                    title={added ? "Already in the list" : "Add to manual list"}
                    onClick={() => onAdd(m.model)}
                    disabled={added}
                  />
                ) : null}
              </Flex>
              <Flex align="center" gap="2" wrap="wrap">
                <Badge color="gray">{m.provider}</Badge>
                <Stat label="ctx" value={fmtCtx(m.context_window)} />
                <Stat label="in" value={fmtUsd(m.input)} />
                <Stat label="out" value={fmtUsd(m.output)} />
                {m.cacheRead != null ? (
                  <Stat label="cache" value={fmtUsd(m.cacheRead)} />
                ) : null}
              </Flex>
            </Flex>
          );
        })}
        {rows.length === 0 ? (
          <Text className="px-1 py-2 text-[12px] text-gray-10">
            No models match “{q}”.
          </Text>
        ) : null}
      </Flex>
    </Flex>
  );
}

// --- small presentational helpers ---

function CostInline({ m }: { m: ModelCatalogEntry }) {
  return (
    <Text className="shrink-0 text-[11px] text-gray-10">
      in {fmtUsd(m.input)} · out {fmtUsd(m.output)}
      <span className="text-gray-9"> /Mtok</span>
    </Text>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <Text className="text-[11px] text-gray-10">
      {label} <span className="text-gray-12">{value}</span>
    </Text>
  );
}

function Select({
  label,
  icon,
  value,
  onChange,
  options,
}: {
  label: string;
  icon?: ReactNode;
  value: string;
  onChange: (v: string) => void;
  options: readonly { value: string; title: string; description: string }[];
}) {
  const [open, setOpen] = useState(false);
  const current = options.find((o) => o.value === value) ?? options[0];
  return (
    <Flex direction="column" gap="1">
      <Flex align="center" justify="between" gap="3">
        <Flex align="center" gap="2" className="shrink-0 text-gray-10">
          {icon}
          <Text className="text-[11px] uppercase tracking-wide">{label}</Text>
        </Flex>
        <Popover.Root open={open} onOpenChange={setOpen}>
          <Popover.Trigger>
            <button
              type="button"
              className="inline-flex w-fit items-center gap-2 rounded-(--radius-2) border border-border bg-(--color-panel-solid) px-2.5 py-1.5 text-left hover:border-(--gray-7)"
            >
              <Text className="text-[12.5px] text-gray-12">
                {current?.title}
              </Text>
              <CaretDownIcon size={12} className="shrink-0 text-gray-10" />
            </button>
          </Popover.Trigger>
          <Popover.Content size="1" width="360px" className="p-0">
            <ul className="max-h-72 divide-y divide-(--gray-4) overflow-auto">
              {options.map((o) => (
                <li key={o.value}>
                  <button
                    type="button"
                    onClick={() => {
                      onChange(o.value);
                      setOpen(false);
                    }}
                    aria-current={o.value === value ? "true" : undefined}
                    className={`flex w-full flex-col gap-0.5 px-3 py-2 text-left ${
                      o.value === value
                        ? "bg-(--accent-3)"
                        : "hover:bg-(--gray-3)"
                    }`}
                  >
                    <Text className="text-[12.5px] text-gray-12">
                      {o.title}
                    </Text>
                    <Text className="text-[11px] text-gray-10 leading-snug">
                      {o.description}
                    </Text>
                  </button>
                </li>
              ))}
            </ul>
          </Popover.Content>
        </Popover.Root>
      </Flex>
      {current?.description ? (
        <Text className="text-[11px] text-gray-10 leading-snug">
          {current.description}
        </Text>
      ) : null}
    </Flex>
  );
}

function Seg<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string }[];
}) {
  return (
    <Flex gap="1" wrap="wrap">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => onChange(o.value)}
          className={`rounded-full border px-3 py-1 text-[12px] capitalize ${
            value === o.value
              ? "border-(--accent-7) bg-(--accent-3) text-gray-12"
              : "border-border bg-(--color-panel-solid) text-gray-11 hover:text-gray-12"
          }`}
        >
          {o.label}
        </button>
      ))}
    </Flex>
  );
}

function MiniBtn({
  label,
  title,
  onClick,
  disabled,
}: {
  label: string;
  title: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      disabled={disabled}
      className="rounded-(--radius-1) border border-border px-2 py-0.5 text-[11px] text-gray-11 hover:text-gray-12 disabled:opacity-40"
    >
      {label}
    </button>
  );
}

function Subhead({ children }: { children: ReactNode }) {
  return (
    <Text className="block text-[11px] text-gray-10 uppercase tracking-wide [font-family:var(--font-mono)]">
      {children}
    </Text>
  );
}

function Muted({ children }: { children: ReactNode }) {
  return (
    <Text className="text-[12px] text-gray-10 leading-snug">{children}</Text>
  );
}

function fmtUsd(n: number): string {
  // Fixed precision so the cost column reads consistently ($1.00, $0.075)
  // and survives float noise from the catalog API.
  return `$${n.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  })}`;
}

/**
 * Deterministic JSON: recursively sorts object keys so the dirty check
 * doesn't fire just because the server serialised `spec.models` with a
 * different key order than the locally-built policy. Arrays keep their order.
 */
function stableStringify(value: unknown): string {
  return JSON.stringify(value, (_key, val) =>
    val && typeof val === "object" && !Array.isArray(val)
      ? Object.fromEntries(
          Object.entries(val).sort(([a], [b]) => a.localeCompare(b)),
        )
      : val,
  );
}

function fmtCtx(n: number): string {
  if (n >= 1_000_000) {
    return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  }
  return `${Math.round(n / 1000)}K`;
}
