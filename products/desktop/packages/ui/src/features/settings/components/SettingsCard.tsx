import { cn } from "@posthog/quill";
import type { ReactNode } from "react";

interface SettingsSectionProps {
  label?: string;
  description?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
}

/**
 * A labeled block on a settings page: an eyebrow label above one or more
 * cards. Pages are a stack of these instead of a flat run of divided rows.
 */
export function SettingsSection({
  label,
  description,
  action,
  children,
}: SettingsSectionProps) {
  return (
    <section className="flex flex-col gap-2">
      {(label || action) && (
        <div className="flex items-center justify-between gap-3 px-0.5">
          <div className="flex flex-col gap-0.5">
            {label && (
              <h3 className="font-semibold text-[12px] text-foreground">
                {label}
              </h3>
            )}
            {description && (
              <p className="m-0 text-[12px] text-muted-foreground leading-snug">
                {description}
              </p>
            )}
          </div>
          {action && <div className="shrink-0">{action}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function SettingsCard({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={cn(
        "divide-y divide-border rounded-(--radius-3) border border-border bg-card",
        className,
      )}
    >
      {children}
    </div>
  );
}

interface SettingsCardRowProps {
  label: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  stacked?: boolean;
}

export function SettingsCardRow({
  label,
  description,
  children,
  stacked = false,
}: SettingsCardRowProps) {
  return (
    <div
      className={cn(
        "flex min-h-11 gap-2 px-3.5 py-2",
        stacked ? "flex-col" : "flex-row items-center justify-between gap-6",
      )}
    >
      <div className="flex min-w-0 flex-col gap-0.5 py-0.5">
        <span className="font-medium text-[13px] text-foreground leading-snug">
          {label}
        </span>
        {description && (
          <span className="text-[12px] text-muted-foreground leading-snug">
            {description}
          </span>
        )}
      </div>
      {children && (
        <div
          className={cn(
            "min-w-0",
            !stacked && "flex shrink-0 items-center justify-end",
          )}
        >
          {children}
        </div>
      )}
    </div>
  );
}
