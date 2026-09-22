import { ArrowSquareOutIcon } from "@phosphor-icons/react";
import {
  Button,
  cn,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";
import { GithubConnectionIcon } from "@posthog/ui/features/integrations/components/GithubConnectionIcon";
import { openUrlInBrowser } from "@posthog/ui/utils/browser";
import type { ReactNode } from "react";

const GITHUB_DOCS_URL = "https://posthog.com/docs/libraries/github?tab=Desktop";

interface GithubConnectionEmptyProps {
  connected: boolean;
  description: ReactNode;
  children?: ReactNode;
  descriptionClassName?: string;
  loading?: boolean;
  showLearnMore?: boolean;
  title?: ReactNode;
  className?: string;
}

export function GithubConnectionEmpty({
  connected,
  description,
  children,
  descriptionClassName,
  loading = false,
  showLearnMore = true,
  title,
  className,
}: GithubConnectionEmptyProps) {
  return (
    <Empty className={cn("py-6", className)} aria-live="polite">
      <EmptyHeader>
        <EmptyMedia>
          <GithubConnectionIcon connected={connected} loading={loading} />
        </EmptyMedia>
        {title ? <EmptyTitle>{title}</EmptyTitle> : null}
        <EmptyDescription className={descriptionClassName}>
          {description}
        </EmptyDescription>
      </EmptyHeader>
      {(children || showLearnMore) && (
        <EmptyContent
          className={
            showLearnMore
              ? "flex-row justify-center gap-2"
              : "w-full max-w-none items-stretch"
          }
        >
          {children}
          {showLearnMore && (
            <Button
              type="button"
              variant="link-muted"
              onClick={() => void openUrlInBrowser(GITHUB_DOCS_URL)}
            >
              Learn more
              <ArrowSquareOutIcon size={12} />
            </Button>
          )}
        </EmptyContent>
      )}
    </Empty>
  );
}
