import { SparkleIcon, XIcon } from "@phosphor-icons/react";
import type { ScoutSuggestionItem } from "@posthog/api-client/posthog-client";
import { buildScoutSuggestionRefinePrompt } from "@posthog/core/scouts/scoutPrompts";
import {
  suggestionCadenceLabel,
  suggestionMetaLine,
} from "@posthog/core/scouts/scoutSuggestions";
import {
  Badge,
  Button,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import type { ScoutSuggestionSurface, ScoutSurface } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { track } from "@posthog/ui/shell/analytics";
import { useScoutChatTask } from "../hooks/useScoutChatTask";

/** How much of a drafted scout body the expanded card shows before pointing at the full draft. */
const DRAFT_PREVIEW_CHARS = 400;

/** The scout surfaces the suggestion cards sit on, in the chat events' own terms. */
const CHAT_SURFACE: Record<ScoutSuggestionSurface, ScoutSurface> = {
  strip: "fleet_list",
  empty_state: "empty_state",
};

export interface ScoutSuggestionCardProps {
  item: ScoutSuggestionItem;
  surface: ScoutSuggestionSurface;
  /** True while one of this card's requests is out. */
  isBusy: boolean;
  isExpanded: boolean;
  onToggleExpanded: () => void;
  onDismiss: () => void;
  /** Turn a canonical pick on, or create a custom one from its draft. */
  onActivate: () => void;
}

/**
 * One suggested scout: what it would watch, why it was picked for this project,
 * and the three ways to act on it. Clicking the body expands it in place, so
 * reading the whole draft never leaves the roster.
 */
export function ScoutSuggestionCard({
  item,
  surface,
  isBusy,
  isExpanded,
  onToggleExpanded,
  onDismiss,
  onActivate,
}: ScoutSuggestionCardProps) {
  const isCanonical = item.kind === "canonical";

  return (
    <div className="relative flex flex-col gap-2 rounded-(--radius-3) border border-border bg-(--color-panel-solid) p-3">
      <Tooltip>
        <TooltipTrigger
          render={
            <Button
              type="button"
              size="icon-xs"
              variant="default"
              aria-label={`Dismiss ${item.title}`}
              disabled={isBusy}
              onClick={onDismiss}
              className="absolute top-1 right-1"
            >
              <XIcon size={12} />
            </Button>
          }
        />
        <TooltipContent side="top">
          Dismiss. This won't be suggested again.
        </TooltipContent>
      </Tooltip>
      <button
        type="button"
        onClick={onToggleExpanded}
        aria-expanded={isExpanded}
        className="flex flex-col items-start gap-1.5 pr-6 text-left"
      >
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant={isCanonical ? "completed" : "info"}>
            {isCanonical ? "Turn on" : "New draft"}
          </Badge>
          {item.gap ? <Badge variant="warning">Gap</Badge> : null}
          <span className="text-[11px] text-gray-10">
            {item.confidence} confidence
          </span>
        </div>
        <span className="font-medium text-[13px] text-gray-12 leading-snug">
          {item.title}
        </span>
        <p
          className={`m-0 text-[12px] text-gray-11 leading-snug ${
            isExpanded ? "" : "line-clamp-2"
          }`}
        >
          {item.why_here}
        </p>
      </button>
      {isExpanded ? <SuggestionDetails item={item} /> : null}
      {/* Pushed down so every card in a row puts its buttons on the same line,
          however many lines its evidence takes. */}
      <span className="mt-auto pt-1 text-[11px] text-gray-10">
        {suggestionMetaLine(item.proposed_config)}
      </span>
      <div className="flex flex-wrap items-center gap-1.5">
        <Button
          type="button"
          size="xs"
          variant="primary"
          loading={isBusy}
          onClick={onActivate}
        >
          {isCanonical ? "Turn on" : "Create scout"}
        </Button>
        <RefineWithAiButton item={item} surface={surface} isBusy={isBusy} />
      </div>
    </div>
  );
}

/**
 * Opens a scout authoring chat primed on this draft, so the agent checks and
 * reshapes the pick instead of scanning the project from scratch.
 */
function RefineWithAiButton({
  item,
  surface,
  isBusy,
}: {
  item: ScoutSuggestionItem;
  surface: ScoutSuggestionSurface;
  isBusy: boolean;
}) {
  const { runTask, isRunning } = useScoutChatTask({
    prompt: buildScoutSuggestionRefinePrompt(item),
    taskLabel: "scout authoring task",
    loggerScope: "scout-suggestion-refine",
    chatType: "author_scout",
    surface: CHAT_SURFACE[surface],
    skillName: item.skill_name,
  });

  return (
    <Button
      type="button"
      size="xs"
      variant="outline"
      loading={isRunning}
      disabled={isBusy}
      onClick={() => {
        track(ANALYTICS_EVENTS.SCOUT_SUGGESTION_CLICKED, {
          suggestion_kind: item.kind,
          skill_name: item.skill_name,
          click_target: "refine_with_ai",
          surface,
        });
        void runTask();
      }}
    >
      <SparkleIcon size={12} />
      Refine with AI
    </Button>
  );
}

/** The rest of a suggestion, shown in place once the card is expanded. */
function SuggestionDetails({ item }: { item: ScoutSuggestionItem }) {
  const draftPreview = item.draft_body.slice(0, DRAFT_PREVIEW_CHARS);

  return (
    <div className="flex flex-col gap-2 border-border border-t pt-2">
      {item.description ? (
        <p className="m-0 text-[12px] text-gray-11 leading-snug">
          {item.description}
        </p>
      ) : null}
      <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12px]">
        <dt className="text-gray-10">Name</dt>
        <dd className="m-0 truncate font-mono text-[11px]">
          {item.skill_name}
        </dd>
        <dt className="text-gray-10">Schedule</dt>
        <dd className="m-0">
          Runs {suggestionCadenceLabel(item.proposed_config)}
        </dd>
        <dt className="text-gray-10">Output</dt>
        <dd className="m-0">
          {item.proposed_config.emit
            ? "Files reports to the inbox"
            : "Dry run, files nothing"}
        </dd>
      </dl>
      {draftPreview ? (
        <div className="flex flex-col gap-1">
          <span className="text-[11px] text-gray-10">
            What it would do on every run
          </span>
          <p className="m-0 whitespace-pre-wrap font-mono text-[11px] text-gray-11 leading-snug">
            {draftPreview}
            {item.draft_body.length > DRAFT_PREVIEW_CHARS ? "…" : ""}
          </p>
        </div>
      ) : null}
    </div>
  );
}
