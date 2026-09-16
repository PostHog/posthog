import { CheckIcon, FileMdIcon, PlusIcon } from "@phosphor-icons/react";
import {
  AlertDialog,
  AlertDialogClose,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
  Kbd,
  Text,
  ToggleGroup,
  ToggleGroupItem,
} from "@posthog/quill";
import type { ContextDocumentStore } from "@posthog/ui/features/canvas/hooks/useContextDocumentStore";
import { CodeMirrorEditor } from "@posthog/ui/features/code-editor/components/CodeMirrorEditor";
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
import { useBlocker } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import {
  appendSection,
  BRIEFING_SECTIONS,
  missingSections,
} from "./briefingSections";

interface BriefingEditorProps {
  channelName: string;
  /** The saved text, which is what "unsaved changes" is measured against. */
  knowledge: string;
  /** What the editor opens with; differs from `knowledge` when a section was added. */
  initialDraft: string;
  store: ContextDocumentStore;
  onSave: (knowledge: string) => Promise<void>;
  onDone: () => void;
}

type View = "write" | "preview";

/**
 * CONTEXT.md open for writing, as a full page. The editor takes the height,
 * the sections agents look for sit beside it, and leaving with unsaved text
 * asks first, whether through Cancel or through any other navigation.
 */
export function BriefingEditor({
  channelName,
  knowledge,
  initialDraft,
  store,
  onSave,
  onDone,
}: BriefingEditorProps) {
  const [draft, setDraft] = useState(initialDraft);
  const [view, setView] = useState<View>("write");
  const [confirmingDiscard, setConfirmingDiscard] = useState(false);
  const dirty = draft !== knowledge;
  const missing = useMemo(() => missingSections(draft), [draft]);

  const blocker = useBlocker({
    shouldBlockFn: ({ current, next }) =>
      dirty && current.pathname !== next.pathname,
    enableBeforeUnload: false,
    withResolver: true,
  });

  const save = async () => {
    if (!dirty || store.isSaving) return;
    try {
      await onSave(draft);
    } catch {
      // The store surfaces the failure under the header; the draft stays.
      return;
    }
    onDone();
  };

  const cancel = () => {
    if (dirty) setConfirmingDiscard(true);
    else onDone();
  };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        void save();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  });

  const discardOpen = confirmingDiscard || blocker.status === "blocked";

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <PageHeader>
        <PageHeaderHeading>
          <PageHeaderTitleRow>
            <PageHeaderTitle>CONTEXT.md</PageHeaderTitle>
            <PageHeaderChip icon={<FileMdIcon size={12} />}>
              {dirty ? "Unsaved changes" : "Editing"}
            </PageHeaderChip>
            <PageHeaderActions>
              <ToggleGroup
                value={[view]}
                onValueChange={(next: string[]) => {
                  const picked = next[0];
                  if (picked === "write" || picked === "preview")
                    setView(picked);
                }}
                aria-label="Editor view"
                className="gap-1"
              >
                <ToggleGroupItem value="write" size="sm" variant="outline">
                  Write
                </ToggleGroupItem>
                <ToggleGroupItem value="preview" size="sm" variant="outline">
                  Preview
                </ToggleGroupItem>
              </ToggleGroup>
              {store.isConflict ? (
                <Button variant="outline" size="sm" onClick={store.refetch}>
                  Reload
                </Button>
              ) : null}
              <Button
                variant="outline"
                size="sm"
                onClick={cancel}
                disabled={store.isSaving}
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                size="sm"
                onClick={() => void save()}
                disabled={!dirty}
                loading={store.isSaving}
              >
                Save
                <Kbd className="ml-1">⌘S</Kbd>
              </Button>
            </PageHeaderActions>
          </PageHeaderTitleRow>
          <PageHeaderDescription>
            {store.saveError ? (
              <span className="text-warning-foreground">
                {store.isConflict
                  ? "Someone else saved a newer version while you were writing. Copy your text, reload, and make the change again."
                  : `Could not save: ${store.saveError.message}`}
              </span>
            ) : (
              `Every agent working in ${channelName} reads this first.`
            )}
          </PageHeaderDescription>
        </PageHeaderHeading>
      </PageHeader>

      <div className="@container min-h-0 flex-1">
        <div className="grid h-full @3xl:grid-cols-[minmax(0,1fr)_240px] grid-cols-1 @3xl:grid-rows-1 grid-rows-[auto_minmax(0,1fr)]">
          <div className="min-h-0 min-w-0 @3xl:border-border @3xl:border-r">
            {view === "write" ? (
              <CodeMirrorEditor
                content={draft}
                filePath="CONTEXT.md"
                onContentChange={setDraft}
              />
            ) : (
              <div className="h-full overflow-y-auto">
                <article className="mx-auto w-full max-w-[72ch] px-8 pt-8 pb-24 text-foreground text-sm leading-relaxed">
                  {draft.trim() ? (
                    <MarkdownRenderer content={draft} />
                  ) : (
                    <Text size="sm" variant="muted">
                      Nothing to preview yet. Switch to Write and start typing.
                    </Text>
                  )}
                </article>
              </div>
            )}
          </div>
          <aside className="@3xl:order-none order-first min-w-0 @3xl:overflow-y-auto border-border border-b @3xl:border-b-0 px-6 py-5">
            <div className="flex flex-col gap-4">
              <div className="flex flex-col gap-0.5">
                <Text size="xs" weight="medium">
                  What agents look for
                </Text>
                <Text size="xxs" variant="muted">
                  Each one is a heading. Add the ones that are missing.
                </Text>
              </div>
              <ul className="flex flex-row @3xl:flex-col flex-wrap @3xl:gap-3 gap-2">
                {BRIEFING_SECTIONS.map((section) => {
                  const isMissing = missing.some(
                    (candidate) => candidate.title === section.title,
                  );
                  return (
                    <li
                      key={section.title}
                      className="flex min-w-0 flex-col gap-0.5"
                    >
                      {isMissing ? (
                        <Button
                          variant="outline"
                          size="xs"
                          className="self-start"
                          onClick={() => {
                            setDraft(appendSection(draft, section.title));
                            setView("write");
                          }}
                        >
                          <PlusIcon size={11} />
                          {section.title}
                        </Button>
                      ) : (
                        <span className="flex h-6 items-center gap-1.5 text-foreground text-xs">
                          <CheckIcon
                            size={12}
                            className="text-success-foreground"
                          />
                          {section.title}
                        </span>
                      )}
                      <Text
                        size="xxs"
                        variant="muted"
                        className="@3xl:block hidden pl-5"
                      >
                        {section.hint}
                      </Text>
                    </li>
                  );
                })}
              </ul>
            </div>
          </aside>
        </div>
      </div>

      <AlertDialog
        open={discardOpen}
        onOpenChange={(open) => {
          if (open) return;
          setConfirmingDiscard(false);
          if (blocker.status === "blocked") blocker.reset();
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Discard your changes?</AlertDialogTitle>
            <AlertDialogDescription>
              CONTEXT.md keeps the saved version. What you wrote since then is
              lost.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogClose render={<Button variant="outline" />}>
              Keep editing
            </AlertDialogClose>
            <Button
              variant="destructive"
              onClick={() => {
                setConfirmingDiscard(false);
                if (blocker.status === "blocked") blocker.proceed();
                else onDone();
              }}
            >
              Discard
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
