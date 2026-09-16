import {
  ArrowSquareOutIcon,
  FileMdIcon,
  PencilSimpleIcon,
  PlusIcon,
  SparkleIcon,
} from "@phosphor-icons/react";
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
import type { ContextDocumentStore } from "@posthog/ui/features/canvas/hooks/useContextDocumentStore";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import {
  PageHeader,
  PageHeaderActions,
  PageHeaderChip,
  PageHeaderDescription,
  PageHeaderHeading,
  PageHeaderTitle,
  PageHeaderTitleRow,
} from "@posthog/ui/primitives/PageHeader";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { type ReactNode, useMemo } from "react";
import type { Components } from "react-markdown";
import {
  appendSection,
  BRIEFING_TEMPLATE,
  headingAnchor,
  missingSections,
  sectionHeadings,
} from "./briefingSections";

interface BriefingReaderProps {
  channelName: string;
  knowledge: string;
  store: ContextDocumentStore;
  /** Open the editor. A seed replaces the document as the starting draft. */
  onEdit: (seed?: string) => void;
  onAskAgent: () => void;
  onOpenInWiki?: () => void;
}

function textOf(node: ReactNode): string {
  if (node === null || node === undefined || typeof node === "boolean") {
    return "";
  }
  if (typeof node === "string" || typeof node === "number") {
    return String(node);
  }
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (typeof node === "object" && "props" in node) {
    const props = node.props as { children?: ReactNode };
    return textOf(props.children);
  }
  return "";
}

// The briefing is a document, not a chat message: headings in the foreground
// with a real scale, anchored so the outline can jump to them.
const READER_COMPONENTS: Partial<Components> = {
  h1: ({ children }) => (
    <h2
      id={headingAnchor(textOf(children))}
      className="mt-8 mb-3 scroll-mt-6 font-semibold text-foreground text-lg first:mt-0"
    >
      {children}
    </h2>
  ),
  h2: ({ children }) => (
    <h3
      id={headingAnchor(textOf(children))}
      className="mt-8 mb-2 scroll-mt-6 font-semibold text-base text-foreground first:mt-0"
    >
      {children}
    </h3>
  ),
  h3: ({ children }) => (
    <h4 className="mt-5 mb-1.5 font-medium text-foreground text-sm first:mt-0">
      {children}
    </h4>
  ),
};

/**
 * CONTEXT.md as its own page: the text at a reading measure, with an outline
 * beside it. Everything that changes the document leaves this view, so what
 * is on screen is always what agents read.
 */
export function BriefingReader({
  channelName,
  knowledge,
  store,
  onEdit,
  onAskAgent,
  onOpenInWiki,
}: BriefingReaderProps) {
  const hasKnowledge = knowledge.trim().length > 0;
  const headings = useMemo(() => sectionHeadings(knowledge), [knowledge]);
  const missing = useMemo(() => missingSections(knowledge), [knowledge]);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <PageHeader>
        <PageHeaderHeading>
          <PageHeaderTitleRow>
            <PageHeaderTitle>CONTEXT.md</PageHeaderTitle>
            {store.versionLabel ? (
              <PageHeaderChip icon={<FileMdIcon size={12} />}>
                {store.versionLabel}
              </PageHeaderChip>
            ) : null}
            {store.isRefreshing ? (
              <Spinner size="xs" aria-hidden="true" />
            ) : null}
            <PageHeaderActions>
              {onOpenInWiki ? (
                <Button variant="outline" size="sm" onClick={onOpenInWiki}>
                  <ArrowSquareOutIcon size={14} />
                  Open in wiki
                </Button>
              ) : null}
              {hasKnowledge ? (
                <>
                  <Button variant="outline" size="sm" onClick={onAskAgent}>
                    <SparkleIcon size={14} />
                    Update with agent
                  </Button>
                  <Button variant="primary" size="sm" onClick={() => onEdit()}>
                    <PencilSimpleIcon size={14} />
                    Edit
                  </Button>
                </>
              ) : null}
            </PageHeaderActions>
          </PageHeaderTitleRow>
          <PageHeaderDescription>
            Every agent working in {channelName} reads this first.
            {store.updatedAt ? (
              <>
                {" · Updated "}
                <RelativeTimestamp timestamp={store.updatedAt} />
              </>
            ) : null}
          </PageHeaderDescription>
        </PageHeaderHeading>
      </PageHeader>

      {hasKnowledge ? (
        <div className="@container min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto grid w-full max-w-[1100px] @3xl:grid-cols-[minmax(0,1fr)_220px] grid-cols-1 @3xl:gap-16 gap-8 px-8 pt-8 pb-24">
            <article className="min-w-0 @3xl:max-w-[72ch] text-foreground text-sm leading-relaxed">
              <MarkdownRenderer
                content={knowledge}
                componentsOverride={READER_COMPONENTS}
              />
            </article>
            <aside className="@3xl:order-none order-first min-w-0">
              <div className="@3xl:sticky @3xl:top-0 flex flex-col gap-6">
                {headings.length > 0 ? (
                  <nav
                    aria-label="On this page"
                    className="flex flex-col gap-1.5"
                  >
                    <Text size="xxs" weight="medium" variant="muted">
                      On this page
                    </Text>
                    <ol className="flex flex-row @3xl:flex-col flex-wrap @3xl:gap-0.5 gap-x-4 gap-y-1">
                      {headings.map((heading) => (
                        <li key={heading}>
                          <button
                            type="button"
                            onClick={() =>
                              document
                                .getElementById(headingAnchor(heading))
                                ?.scrollIntoView({
                                  block: "start",
                                  behavior: "smooth",
                                })
                            }
                            className="truncate text-left text-muted-foreground text-xs transition-colors hover:text-foreground"
                          >
                            {heading}
                          </button>
                        </li>
                      ))}
                    </ol>
                  </nav>
                ) : null}
                {missing.length > 0 ? (
                  <div className="flex flex-col gap-1.5">
                    <Text size="xxs" weight="medium" variant="muted">
                      Not written yet
                    </Text>
                    <ul className="flex flex-row @3xl:flex-col flex-wrap gap-1.5">
                      {missing.map((section) => (
                        <li key={section.title}>
                          <Button
                            variant="outline"
                            size="xs"
                            title={section.hint}
                            onClick={() =>
                              onEdit(appendSection(knowledge, section.title))
                            }
                          >
                            <PlusIcon size={11} />
                            {section.title}
                          </Button>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </div>
            </aside>
          </div>
        </div>
      ) : (
        <Empty className="flex-1">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <FileMdIcon size={28} />
            </EmptyMedia>
            <EmptyTitle>Nothing written yet</EmptyTitle>
            <EmptyDescription>
              Tell agents what {channelName} is, how to work here, which files
              matter, and what is not obvious from the code.
            </EmptyDescription>
          </EmptyHeader>
          <EmptyContent className="flex-row justify-center">
            <Button variant="primary" onClick={() => onEdit(BRIEFING_TEMPLATE)}>
              <PencilSimpleIcon size={14} />
              Write it
            </Button>
            <Button variant="outline" onClick={onAskAgent}>
              <SparkleIcon size={14} />
              Draft with agent
            </Button>
          </EmptyContent>
        </Empty>
      )}
    </div>
  );
}
