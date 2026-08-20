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
import type { ArtifactEditConflict } from "./useArtifactEditing";

export function ArtifactEditView({
  name,
  source,
  editorPath,
  showRendered,
  saving,
  conflict,
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
  conflict: ArtifactEditConflict | null;
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
      <AlertDialog
        open={conflict !== null}
        onOpenChange={(open) => {
          if (!saving) onConflictOpenChange(open);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {conflict === "dismissed"
                ? "This file was dismissed"
                : "A newer version is available"}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {conflict === "dismissed"
                ? "Every version of this file was dismissed while you were editing. Save your changes to restore it as the latest version?"
                : "A newer version of this file arrived while you were editing. Save yours as the latest anyway?"}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogClose
              disabled={saving}
              render={<Button variant="outline" disabled={saving} />}
            >
              Keep editing
            </AlertDialogClose>
            <Button variant="primary" loading={saving} onClick={onForceSave}>
              {conflict === "dismissed" ? "Save and restore" : "Save as latest"}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
