import {
  fileDisplayName,
  fileTitle,
  newFileContent,
} from "@posthog/core/canvas/contextFiles";
import { useWikiContextDocumentStore } from "@posthog/ui/features/canvas/hooks/useContextDocumentStore";
import { MarkdownFileDialog } from "./MarkdownFileDialog";

interface SpaceFileDialogProps {
  path: string;
  channelName: string;
  onClose: () => void;
}

/** A space's extra Markdown file, edited where it lives in the context wiki. */
export function SpaceFileDialog({
  path,
  channelName,
  onClose,
}: SpaceFileDialogProps) {
  const store = useWikiContextDocumentStore(path);
  const name = fileDisplayName(path);
  return (
    <MarkdownFileDialog
      fileName={name}
      description={`Saved beside CONTEXT.md. Agents in ${channelName} read it with the rest of the context.`}
      store={store}
      template={newFileContent(fileTitle(name))}
      onClose={onClose}
    />
  );
}
