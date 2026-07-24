import type {
  PermissionOption,
  SessionConfigOption,
} from "@agentclientprotocol/sdk";
import type { ExecutionMode } from "@posthog/shared";
import { ModeSelector } from "@posthog/ui/features/message-editor/components/ModeSelector";
import { MODE_LABELS } from "@posthog/ui/features/sessions/modeStyles";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import {
  ActionSelector,
  InlineEditableText,
} from "@posthog/ui/primitives/ActionSelector";
import { Box, Flex, Text } from "@radix-ui/themes";
import { useEffect, useMemo, useRef, useState } from "react";
import { type BasePermissionProps, toSelectorOptions } from "./types";

const TITLE = "Implementation Plan";
const QUESTION = "Approve this plan to proceed?";

function isApprove(option: PermissionOption): boolean {
  return option.kind === "allow_once" || option.kind === "allow_always";
}

function isReject(option: PermissionOption): boolean {
  return option.kind === "reject_once" || option.kind === "reject_always";
}

function hasCustomInput(option: PermissionOption): boolean {
  return (
    (option._meta as { customInput?: boolean } | null | undefined)
      ?.customInput === true
  );
}

// Don't steal focus from an interactive element in a different grid cell
// (multi-task view). Mirrors the guard in useActionSelectorState.
function isInteractiveElementInDifferentCell(
  containerRef: React.RefObject<HTMLDivElement | null>,
): boolean {
  const el = document.activeElement;
  if (!(el instanceof HTMLElement)) return false;
  const isInteractive =
    el.tagName === "INPUT" ||
    el.tagName === "TEXTAREA" ||
    el.tagName === "SELECT" ||
    el.getAttribute("contenteditable") === "true";
  if (!isInteractive) return false;
  const activeCell = el.closest("[data-grid-cell]");
  const ownCell = containerRef.current?.closest("[data-grid-cell]");
  if (!activeCell || !ownCell) return true;
  return activeCell !== ownCell;
}

/**
 * Plan-approval selector: keeps the original stacked-list shape — an "Approve"
 * line on top and the inline reject-with-feedback line below — but collapses
 * the per-mode "Yes, and…" rows into the shared prompt-input `ModeSelector`
 * dropdown beside the Approve line. Everything is derived from the permission
 * `options` and reported through `onSelect`/`onCancel`, so there is no backend
 * contract change: approve → `onSelect(<modeOptionId>)`, reject →
 * `onSelect(<rejectOptionId>, feedback)`.
 */
export function PlanApprovalSelector({
  toolCall,
  options,
  onSelect,
  onCancel,
}: BasePermissionProps) {
  const approveOptions = useMemo(() => options.filter(isApprove), [options]);
  const rejectOption = useMemo(
    () =>
      options.find((o) => isReject(o) && hasCustomInput(o)) ??
      options.find(isReject),
    [options],
  );

  const lastApprovalMode = useSettingsStore((s) => s.lastPlanApprovalMode);
  const setLastApprovalMode = useSettingsStore(
    (s) => s.setLastPlanApprovalMode,
  );

  // Resolution order: the mode last approved with (remembered preference),
  // then "auto", then manual-approve, then any single-use mode, then the first.
  // Settings persist asynchronously (an IPC round trip on desktop), so
  // `lastApprovalMode` can still be its pre-hydration default on mount — e.g.
  // resuming a task with an already-pending plan approval. Recomputing this
  // via `useMemo` (rather than seeding a `useState` once) means it stays
  // correct once the store finishes hydrating.
  const initialMode = useMemo(() => {
    const has = (id: string) => approveOptions.some((o) => o.optionId === id);
    return (
      (lastApprovalMode && has(lastApprovalMode)
        ? lastApprovalMode
        : undefined) ??
      (has("auto") ? "auto" : undefined) ??
      approveOptions.find((o) => o.optionId === "default")?.optionId ??
      approveOptions.find((o) => o.kind === "allow_once")?.optionId ??
      approveOptions[0]?.optionId
    );
  }, [approveOptions, lastApprovalMode]);

  // Only the user's own pick lives in state; everything else derives from
  // `initialMode` so it tracks `lastApprovalMode` live instead of freezing it
  // at mount — derive it, don't duplicate it.
  const [explicitMode, setExplicitMode] = useState<string | undefined>(
    undefined,
  );
  // This component can survive to a later approval request without
  // remounting, so a pick made for the previous request must not leak into
  // (and potentially not exist in) this one. Reset during render rather than
  // in an effect: it takes effect before this render paints instead of one
  // render later, avoiding a flash of the stale mode.
  const lastToolCallIdRef = useRef(toolCall.toolCallId);
  if (lastToolCallIdRef.current !== toolCall.toolCallId) {
    lastToolCallIdRef.current = toolCall.toolCallId;
    setExplicitMode(undefined);
  }
  const selectedMode = explicitMode ?? initialMode;
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const [feedback, setFeedback] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);

  const rejectIndex = rejectOption ? 1 : -1;
  const rowCount = rejectOption ? 2 : 1;
  // The reject row is the inline feedback textarea, so "on the reject row" and
  // "editing feedback" are the same state — derive it, don't duplicate it.
  const rejectSelected = selectedIndex === rejectIndex;

  // A `SessionConfigOption` shaped for the shared `ModeSelector` — reusing that
  // component (rather than a bespoke dropdown) keeps styling/theming identical
  // to the prompt-input mode selector. The backend already gates which modes
  // appear, so bypass filtering isn't reapplied here.
  const modeConfigOption = useMemo<SessionConfigOption>(
    () => ({
      type: "select",
      id: "plan-approval-mode",
      name: "Mode",
      category: "mode",
      currentValue: selectedMode ?? "",
      options: approveOptions.map((o) => ({
        value: o.optionId,
        name: MODE_LABELS[o.optionId] ?? o.name,
      })),
    }),
    [selectedMode, approveOptions],
  );

  // Focus the action row on mount so keyboard nav works immediately, unless a
  // different grid cell (multi-task view) already owns focus. Selection-driven
  // focus is handled inline in `selectRow`, not via a state-syncing effect.
  useEffect(() => {
    if (!isInteractiveElementInDifferentCell(containerRef)) {
      containerRef.current?.focus();
    }
  }, []);

  // Move selection and manage focus together (no state-syncing effect): the
  // approve row focuses the container for keyboard nav; the reject row's
  // textarea focuses itself via its `active` prop.
  const selectRow = (index: number) => {
    setHoveredIndex(null);
    setSelectedIndex(index);
    if (index !== rejectIndex) containerRef.current?.focus();
  };

  const approve = () => {
    if (!selectedMode) return;
    // Remember this choice so the next plan approval pre-selects it.
    setLastApprovalMode(selectedMode as ExecutionMode);
    onSelect(selectedMode);
  };

  const submitReject = () => {
    const text = feedback.trim();
    // Exactly as before: reject requires feedback text; empty Enter is a no-op
    // (use Esc to dismiss the request without feedback).
    if (!rejectOption || !text) return;
    onSelect(rejectOption.optionId, text);
  };

  const moveSelection = (delta: number) => {
    selectRow((selectedIndex + delta + rowCount) % rowCount);
  };

  const handleContainerKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    // The reject textarea owns the keyboard while it's the selected row.
    if (rejectSelected) return;
    switch (e.key) {
      case "ArrowUp":
        e.preventDefault();
        moveSelection(-1);
        break;
      case "ArrowDown":
        e.preventDefault();
        moveSelection(1);
        break;
      case "Enter":
        e.preventDefault();
        approve();
        break;
      case "Escape":
        e.preventDefault();
        e.stopPropagation();
        onCancel();
        break;
      default:
        if (/^[1-9]$/.test(e.key) && !e.metaKey && !e.ctrlKey) {
          const idx = Number.parseInt(e.key, 10) - 1;
          if (idx < rowCount) {
            e.preventDefault();
            if (idx === 0) approve();
            else selectRow(idx);
          }
        }
    }
  };

  // Degenerate case (a plan always has approve options): fall back to the
  // generic list so the request stays actionable.
  if (!selectedMode) {
    return (
      <ActionSelector
        title={TITLE}
        question={QUESTION}
        options={toSelectorOptions(options)}
        onSelect={onSelect}
        onCancel={onCancel}
      />
    );
  }

  const rowClass = (index: number) => {
    const bg =
      selectedIndex === index
        ? "bg-primary/10"
        : hoveredIndex === index
          ? "bg-fill-hover"
          : "bg-transparent";
    return `-mx-3 cursor-pointer select-none rounded-(--radius-2) pt-[4px] pr-3 pb-[4px] pl-3 ${bg}`;
  };

  const caret = (index: number) => (
    <Text
      className={`w-[1ch] shrink-0 text-[13px] leading-4 ${selectedIndex === index ? "text-primary" : "text-gray-11"}`}
    >
      {selectedIndex === index ? "›" : ""}
    </Text>
  );

  const number = (index: number) => (
    <Text
      className={`min-w-[16px] shrink-0 whitespace-nowrap text-right text-[13px] leading-4 ${
        selectedIndex === index || hoveredIndex === index
          ? "text-primary"
          : "text-gray-11"
      }`}
    >
      {index + 1}.
    </Text>
  );

  const approveActive = selectedIndex === 0 || hoveredIndex === 0;

  return (
    <Box
      ref={containerRef}
      tabIndex={0}
      onKeyDown={handleContainerKeyDown}
      onClick={(e) => {
        if (e.target === containerRef.current) containerRef.current?.focus();
      }}
      p="3"
      className="rounded-(--radius-3) border border-(--gray-6) bg-(--gray-1) outline-none"
    >
      <Flex direction="column" gap="2">
        <Text className="font-medium text-[13px] text-primary">{TITLE}</Text>

        <Box>
          <Text mb="2" as="p" className="text-[13px]">
            {QUESTION}
          </Text>

          <Flex direction="column" gap="1" px="2">
            {/* Approve line — mode dropdown (shared ModeSelector) beside it. */}
            <Box
              onClick={approve}
              onMouseEnter={() => setHoveredIndex(0)}
              onMouseLeave={() => setHoveredIndex(null)}
              py="1"
              className={rowClass(0)}
            >
              <Flex align="center" gap="2" className="leading-4">
                {caret(0)}
                {number(0)}
                <Flex
                  align="center"
                  justify="between"
                  gap="2"
                  className="min-w-0 flex-1 leading-4"
                >
                  <Text
                    className={`whitespace-pre-wrap font-medium text-[13px] leading-4 ${approveActive ? "text-primary" : "text-gray-12"}`}
                  >
                    Approve and proceed
                  </Text>
                  <Box onClick={(e) => e.stopPropagation()}>
                    <ModeSelector
                      modeOption={modeConfigOption}
                      onChange={(value) => setExplicitMode(value)}
                      allowBypassPermissions
                    />
                  </Box>
                </Flex>
              </Flex>
            </Box>

            {/* Reject line — the inline feedback textarea, exactly as before. */}
            {rejectOption && (
              <Box
                onClick={() => selectRow(1)}
                onMouseEnter={() => setHoveredIndex(1)}
                onMouseLeave={() => setHoveredIndex(null)}
                py="1"
                className={rowClass(1)}
              >
                <Flex align="center" gap="2" className="leading-4">
                  {caret(1)}
                  {number(1)}
                  <Box className="min-w-0 flex-1 leading-4">
                    <InlineEditableText
                      value={feedback}
                      placeholder="Type here to tell the agent what to do differently"
                      active={rejectSelected}
                      onChange={setFeedback}
                      onNavigateUp={() => selectRow(0)}
                      onNavigateDown={() => selectRow(0)}
                      onEscape={() => {
                        setFeedback("");
                        selectRow(0);
                      }}
                      onSubmit={submitReject}
                    />
                  </Box>
                </Flex>
              </Box>
            )}
          </Flex>

          <Text color="gray" mt="2" as="p" className="text-[13px]">
            Enter to select · ↑↓ to navigate · Esc to cancel
          </Text>
        </Box>
      </Flex>
    </Box>
  );
}
