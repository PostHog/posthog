import { FileMdIcon } from "@phosphor-icons/react";
import {
  AlertDialog,
  AlertDialogClose,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Kbd,
  Text,
} from "@posthog/quill";
import type { ContextDocumentStore } from "@posthog/ui/features/canvas/hooks/useContextDocumentStore";
import { CodeMirrorEditor } from "@posthog/ui/features/code-editor/components/CodeMirrorEditor";
import { LoadingState } from "@posthog/ui/primitives/LoadingState";
import { useEffect, useState } from "react";

interface MarkdownFileDialogProps {
  fileName: string;
  description: string;
  store: ContextDocumentStore;
  /** What the editor opens with when the file is empty. */
  template?: string;
  onClose: () => void;
}

/**
 * One Markdown file, as text, in a modal: the editor, Save, Cancel. There is
 * no preview, because the file is what agents read and what a person should
 * see. Closing with unsaved text asks first.
 */
export function MarkdownFileDialog({
  fileName,
  description,
  store,
  template,
  onClose,
}: MarkdownFileDialogProps) {
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        size="wide"
        className="h-[760px] grid-rows-[auto_minmax(0,1fr)_auto]"
        showCloseButton={false}
      >
        {store.isLoading ? (
          <>
            <FileHeader
              fileName={fileName}
              description={description}
              dirty={false}
            />
            <LoadingState />
            <DialogFooter>
              <Button variant="outline" size="sm" onClick={onClose}>
                Cancel
              </Button>
            </DialogFooter>
          </>
        ) : (
          <Editor
            fileName={fileName}
            description={description}
            store={store}
            template={template}
            onClose={onClose}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

function Editor({
  fileName,
  description,
  store,
  template,
  onClose,
}: MarkdownFileDialogProps) {
  const saved = store.content;
  const [draft, setDraft] = useState(
    saved.trim() ? saved : (template ?? saved),
  );
  const [confirmingDiscard, setConfirmingDiscard] = useState(false);
  const [reloading, setReloading] = useState(false);
  const dirty = draft !== saved;

  const reload = () => {
    setReloading(true);
    store.refetch();
  };

  // The draft is replaced only once the newer copy has arrived, so a reload
  // after a conflict shows what the other person saved rather than a blank.
  useEffect(() => {
    if (reloading && !store.isRefreshing) {
      setDraft(saved);
      setReloading(false);
    }
  }, [reloading, store.isRefreshing, saved]);

  const save = async () => {
    if (!dirty || store.isSaving) return;
    try {
      await store.save(draft);
      onClose();
    } catch {
      // The store keeps the error; the footer shows it.
    }
  };

  const cancel = () => {
    if (dirty) setConfirmingDiscard(true);
    else onClose();
  };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key === "s") {
        event.preventDefault();
        void save();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  });

  return (
    <>
      <FileHeader fileName={fileName} description={description} dirty={dirty} />
      <div className="min-h-0 overflow-hidden border-border border-y">
        <CodeMirrorEditor
          content={draft}
          filePath={fileName}
          onContentChange={setDraft}
        />
      </div>
      <DialogFooter className="items-center sm:justify-between">
        <div className="min-w-0 flex-1">
          {store.saveError ? (
            <Text size="xs" className="text-warning-foreground">
              {store.isConflict
                ? "Someone else saved a newer version while you were writing. Copy anything you want to keep, then reload and make the change again."
                : `Could not save: ${store.saveError.message}`}
            </Text>
          ) : store.error ? (
            <Text size="xs" className="text-warning-foreground">
              Could not load the saved copy: {store.error.message}
            </Text>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {store.isConflict ? (
            <Button
              variant="outline"
              size="sm"
              onClick={reload}
              loading={reloading}
            >
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
        </div>
      </DialogFooter>

      <AlertDialog
        open={confirmingDiscard}
        onOpenChange={(open) => !open && setConfirmingDiscard(false)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Discard your changes?</AlertDialogTitle>
            <AlertDialogDescription>
              {fileName} keeps its saved text. What you typed here is lost.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogClose render={<Button variant="outline" />}>
              Keep editing
            </AlertDialogClose>
            <Button variant="destructive" onClick={onClose}>
              Discard
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

function FileHeader({
  fileName,
  description,
  dirty,
}: {
  fileName: string;
  description: string;
  dirty: boolean;
}) {
  return (
    <DialogHeader>
      <DialogTitle className="flex items-center gap-2">
        <FileMdIcon size={16} />
        <span className="font-mono">{fileName}</span>
        {dirty ? (
          <Text size="xxs" variant="muted" className="font-normal">
            Unsaved changes
          </Text>
        ) : null}
      </DialogTitle>
      <DialogDescription>{description}</DialogDescription>
    </DialogHeader>
  );
}
