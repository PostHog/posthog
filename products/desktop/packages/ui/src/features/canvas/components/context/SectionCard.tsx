import { Badge, cn, Heading, Text } from "@posthog/quill";
import type { ReactNode } from "react";

interface SectionCardProps {
  icon: ReactNode;
  title: string;
  description: string;
  count?: number;
  actions?: ReactNode;
  /** Drop the card frame; the section body brings its own surfaces. */
  flush?: boolean;
  children: ReactNode;
}

/** One part of the Context page: a titled header row and a framed body. */
export function SectionCard({
  icon,
  title,
  description,
  count,
  actions,
  flush = false,
  children,
}: SectionCardProps) {
  return (
    <section className="flex flex-col gap-3">
      <header className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
            {icon}
          </span>
          <div className="flex min-w-0 flex-col gap-0.5">
            <div className="flex items-center gap-2">
              <Heading size="sm">{title}</Heading>
              {count !== undefined && count > 0 ? (
                <Badge variant="default">{count}</Badge>
              ) : null}
            </div>
            <Text size="xs" variant="muted">
              {description}
            </Text>
          </div>
        </div>
        {actions ? (
          <div className="flex shrink-0 items-center gap-2">{actions}</div>
        ) : null}
      </header>
      <div
        className={cn(
          !flush && "overflow-hidden rounded-lg border border-border bg-card",
        )}
      >
        {children}
      </div>
    </section>
  );
}

/** A quiet in-card placeholder for a section that has nothing yet. */
export function SectionPlaceholder({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-2 px-6 py-8 text-center",
        className,
      )}
    >
      {children}
    </div>
  );
}
