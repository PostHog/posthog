import {
  AlertDialog,
  AlertDialogClose,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
} from "@posthog/quill";
import type { ReactElement } from "react";
import { CodeMirrorEditor } from "../../code-editor/components/CodeMirrorEditor";
import { DocumentPreviewHeader } from "../../code-editor/components/DocumentPreviewHeader";

export function ArtifactEditView({
  name,
  source,
  editorPath,
  showRendered,
  saving,
  conflictOpen,
  onConflictOpenChange,
  getContent,
  onContentChange,
  onCancel,
  onSave,
  onForceSave,
}: {
  name: string;
  source: string;
  editorPath: string;
  showRendered: boolean;
  saving: boolean;
  conflictOpen: boolean;
  onConflictOpenChange: (open: boolean) => void;
  getContent: () => string;
  onContentChange: (content: string) => void;
  onCancel: () => void;
  onSave: () => void;
  onForceSave: () => void;
}): ReactElement {
  return (
    <div className="flex h-full flex-col overflow-hidden">
      <DocumentPreviewHeader
        label={name}
        content={source}
        getContent={getContent}
        showRendered={showRendered}
        editing
        saving={saving}
        onCancel={onCancel}
        onSave={onSave}
      />
      <div className="min-h-0 min-w-0 flex-1 overflow-hidden">
        <CodeMirrorEditor
          content={source}
          filePath={editorPath}
          readOnly={false}
          onContentChange={onContentChange}
        />
      </div>
      <AlertDialog open={conflictOpen} onOpenChange={onConflictOpenChange}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>A newer version is available</AlertDialogTitle>
            <AlertDialogDescription>
              A newer version of this file arrived while you were editing. Save
              yours as the latest anyway?
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogClose render={<Button variant="outline" />}>
              Keep editing
            </AlertDialogClose>
            <Button variant="primary" loading={saving} onClick={onForceSave}>
              Save as latest
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
