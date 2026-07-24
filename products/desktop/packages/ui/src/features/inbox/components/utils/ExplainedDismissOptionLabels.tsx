import { EyeSlashIcon, Pause } from "@phosphor-icons/react";
import type { DismissalReasonOptionValue } from "@posthog/shared";
import { RadioGroup, Tooltip } from "@radix-ui/themes";
import type { ReactNode } from "react";

const PAUSE_OPTION_TOOLTIP =
  "Snoozes this report: it briefly leaves your inbox while more context is gathered, and it can come back if new findings match.";

const SUPPRESS_OPTION_TOOLTIP =
  "Archives permanently: the report leaves your inbox and matching findings will not surface it again. Your reason is saved with the report.";

function dismissReasonOptionDomId(value: DismissalReasonOptionValue): string {
  return `dismiss-report-dialog-reason-${value}`;
}

interface ExplainedPauseLabelProps {
  label: string;
  value: DismissalReasonOptionValue;
  disabled?: boolean;
  /** When snooze is blocked for this selection, shown instead of the default snooze explanation. */
  disabledReason?: string | null;
}

export function ExplainedPauseLabel({
  label,
  value,
  disabled = false,
  disabledReason,
}: ExplainedPauseLabelProps) {
  const tooltipContent =
    disabled && disabledReason ? disabledReason : PAUSE_OPTION_TOOLTIP;
  const inputId = dismissReasonOptionDomId(value);

  return (
    <ExplainedLabel
      tooltipContent={tooltipContent}
      inputId={inputId}
      optionLabel={label}
      value={value}
      radioDisabled={disabled}
      icon={
        <Pause size={12} className="shrink-0 text-(--gray-9)" aria-hidden />
      }
    />
  );
}

interface ExplainedSuppressLabelProps {
  label: string;
  value: DismissalReasonOptionValue;
}

export function ExplainedSuppressLabel({
  label,
  value,
}: ExplainedSuppressLabelProps) {
  const inputId = dismissReasonOptionDomId(value);

  return (
    <ExplainedLabel
      tooltipContent={SUPPRESS_OPTION_TOOLTIP}
      inputId={inputId}
      optionLabel={label}
      value={value}
      icon={
        <EyeSlashIcon
          size={12}
          className="shrink-0 text-(--gray-9)"
          aria-hidden
        />
      }
    />
  );
}

interface ExplainedLabelProps {
  tooltipContent: ReactNode;
  /** Matches `RadioGroup.Item` `id` / label `htmlFor`. */
  inputId: string;
  optionLabel: string;
  value: DismissalReasonOptionValue;
  icon: ReactNode;
  radioDisabled?: boolean;
}

/**
 * Tooltip + radio row: hover (or keyboard focus on the label copy) explains the option.
 * The radio sits outside the tooltip trigger so dialog autofocus does not open the tooltip.
 */
function ExplainedLabel({
  tooltipContent,
  inputId,
  optionLabel,
  value,
  icon,
  radioDisabled = false,
}: ExplainedLabelProps) {
  const disabledRowClass = radioDisabled ? "cursor-not-allowed opacity-60" : "";

  return (
    <div
      className={`flex min-w-0 max-w-full items-start gap-2 self-start text-[13px] ${disabledRowClass}`}
    >
      <RadioGroup.Item
        id={inputId}
        value={value}
        disabled={radioDisabled}
        className="mt-0.5 shrink-0"
      />
      <Tooltip content={tooltipContent} side="right" align="end">
        <label
          htmlFor={inputId}
          className={`inline-flex min-w-0 max-w-full flex-wrap items-center gap-1.5 ${radioDisabled ? "cursor-not-allowed" : "cursor-pointer"}`}
        >
          <span>{optionLabel}</span>
          {icon}
        </label>
      </Tooltip>
    </div>
  );
}
