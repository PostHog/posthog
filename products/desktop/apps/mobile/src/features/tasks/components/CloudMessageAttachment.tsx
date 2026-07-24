import {
  type HumanMessageAttachment,
  MarkdownImage,
  MessageFileChip,
} from "@/features/chat";
import { useCloudAttachmentPreview } from "../hooks/useCloudAttachmentPreview";

export function CloudMessageAttachment({
  attachment,
  taskId,
}: {
  attachment: HumanMessageAttachment;
  taskId?: string;
}) {
  const { data: previewUrl } = useCloudAttachmentPreview(
    taskId,
    attachment.cloudArtifact,
  );

  if (attachment.kind !== "image") {
    return <MessageFileChip fileName={attachment.fileName} />;
  }

  // Cloud images resolve to a presigned URL; local (in-flight) images render
  // straight from their device uri. Fall back to a chip when neither is ready.
  const imageUrl = attachment.cloudArtifact ? previewUrl : attachment.uri;
  if (!imageUrl) {
    return <MessageFileChip fileName={attachment.fileName} />;
  }

  return <MarkdownImage url={imageUrl} alt={attachment.fileName} />;
}
