import {
  Button,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Text,
} from "@posthog/quill";
import { hoggiePng } from "@posthog/shared/hoggies";
import { navigateToLoops } from "@posthog/ui/router/navigationBridge";

export function LoopNotFound() {
  return (
    <Empty className="h-full border-0">
      <EmptyHeader>
        <EmptyMedia>
          <img
            src={hoggiePng("magnifying-glass-1")}
            alt=""
            className="pointer-events-none w-28 select-none"
          />
        </EmptyMedia>
        <EmptyTitle>Loop not found</EmptyTitle>
        <EmptyDescription>
          This loop may have been deleted, or it belongs to a different project.
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button
          type="button"
          variant="primary"
          data-attr="loop-not-found-view-all"
          onClick={() => navigateToLoops()}
        >
          View all loops
        </Button>
      </EmptyContent>
    </Empty>
  );
}

export function LoopLoadError() {
  return (
    <div className="mx-auto mt-16 flex max-w-md flex-col items-center gap-1 rounded-(--radius-2) border border-border border-dashed px-6 py-10 text-center">
      <Text size="sm" weight="medium">
        Couldn't load this loop
      </Text>
      <Text size="xs" variant="muted" className="leading-snug">
        It may have been deleted, or the loops API returned an error.
      </Text>
    </div>
  );
}

export function LoopsEmptyNotice({
  title,
  hint,
}: {
  title: string;
  hint: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-1 rounded border border-border border-dashed py-6">
      <Text size="sm" weight="medium">
        {title}
      </Text>
      <Text size="sm" variant="muted" className="max-w-[420px] text-center">
        {hint}
      </Text>
    </div>
  );
}

export function LoopsSkeleton() {
  return (
    <div className="flex flex-col gap-2">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="h-[58px] animate-pulse rounded-(--radius-2) border border-border bg-muted"
        />
      ))}
    </div>
  );
}
