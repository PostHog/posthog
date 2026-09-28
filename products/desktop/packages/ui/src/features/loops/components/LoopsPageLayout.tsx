import {
  PageHeader,
  PageHeaderActions,
  PageHeaderHeading,
  PageHeaderTitle,
  PageHeaderTitleRow,
} from "@posthog/ui/primitives/PageHeader";
import type { ReactNode } from "react";

export function LoopsPageLayout({
  actions,
  children,
  footer,
}: {
  actions: ReactNode;
  children: ReactNode;
  footer: ReactNode;
}) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <PageHeader>
        <PageHeaderHeading>
          <PageHeaderTitleRow>
            <PageHeaderTitle>Loops</PageHeaderTitle>
            <PageHeaderActions>{actions}</PageHeaderActions>
          </PageHeaderTitleRow>
        </PageHeaderHeading>
      </PageHeader>

      <div className="min-h-0 flex-1 overflow-auto">
        <div className="@container mx-auto flex w-full max-w-6xl flex-col gap-8 px-8 pt-6 pb-8">
          {children}
        </div>
      </div>

      <div className="shrink-0">
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-2 px-8 pt-3 pb-6">
          {footer}
        </div>
      </div>
    </div>
  );
}
