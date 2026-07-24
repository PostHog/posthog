import { File } from "@phosphor-icons/react";
import {
  SESSION_SERVICE,
  type SessionService,
} from "@posthog/core/sessions/sessionService";
import { useService } from "@posthog/di/react";
import { isRasterImageFile, parseImageDataUrl } from "@posthog/shared";
import {
  getAuthIdentity,
  useAuthStateValue,
} from "@posthog/ui/features/auth/store";
import { readFileAsDataUrl } from "@posthog/ui/features/message-editor/hostApi";
import { MentionChip } from "@posthog/ui/features/sessions/components/session-update/parseFileMentions";
import type { UserMessageAttachment } from "@posthog/ui/features/sessions/userMessageTypes";
import { useSessionTaskId } from "@posthog/ui/features/sessions/useSessionTaskId";
import { SafeImagePreview } from "@posthog/ui/primitives/SafeImagePreview";
import { Dialog, Text } from "@radix-ui/themes";
import { useQuery } from "@tanstack/react-query";

function attachmentFilePath(id: string): string | null {
  if (id.startsWith("/") || /^[A-Za-z]:[\\/]/.test(id)) return id;
  if (!id.startsWith("file://")) return null;

  try {
    return decodeURIComponent(new URL(id).pathname);
  } catch {
    return null;
  }
}

function ImageAttachment({
  attachment,
}: {
  attachment: UserMessageAttachment;
}) {
  const filePath = attachmentFilePath(attachment.id);
  const taskId = useSessionTaskId();
  const authIdentity = useAuthStateValue(getAuthIdentity);
  const sessionService = useService<SessionService>(SESSION_SERVICE);
  const cloudArtifact = attachment.cloudArtifact;
  const { data: previewUrl } = useQuery({
    queryKey: cloudArtifact
      ? [
          "cloudArtifactPreview",
          authIdentity,
          taskId,
          cloudArtifact.runId,
          cloudArtifact.artifactId,
        ]
      : ["os", "readFileAsDataUrl", filePath],
    queryFn: () => {
      if (cloudArtifact && taskId) {
        return sessionService.getCloudAttachmentPreviewUrl(
          taskId,
          cloudArtifact.runId,
          cloudArtifact.artifactId,
        );
      }
      return readFileAsDataUrl({ filePath: filePath ?? "" });
    },
    enabled: cloudArtifact
      ? taskId !== null && authIdentity !== null
      : filePath !== null,
    retry: false,
    staleTime: cloudArtifact ? 50 * 60 * 1000 : Infinity,
  });
  const parsedImage = previewUrl?.startsWith("data:")
    ? parseImageDataUrl(previewUrl)
    : null;

  if (!previewUrl) {
    return <MentionChip icon={<File size={12} />} label={attachment.label} />;
  }

  return (
    <Dialog.Root>
      <Dialog.Trigger>
        <button
          type="button"
          className="group relative h-16 w-20 overflow-hidden rounded-md border border-gray-6 bg-gray-3"
          aria-label={`Preview ${attachment.label}`}
        >
          <img
            src={previewUrl}
            alt={attachment.label}
            className="size-full object-cover transition-transform group-hover:scale-105"
          />
          <span className="absolute inset-x-0 bottom-0 truncate bg-black/60 px-1.5 py-0.5 text-left text-[10px] text-white">
            {attachment.label}
          </span>
        </button>
      </Dialog.Trigger>
      <Dialog.Content maxWidth="85vw" className="w-fit p-[16px]">
        <Dialog.Title mb="2" className="text-sm">
          {attachment.label}
        </Dialog.Title>
        {parsedImage ? (
          <SafeImagePreview
            base64={parsedImage.base64}
            mimeType={parsedImage.mimeType}
            alt={attachment.label}
            className="max-h-[75vh] max-w-[80vw]"
          />
        ) : previewUrl.startsWith("data:") ? (
          <Text color="gray" className="text-sm">
            Unable to load image preview
          </Text>
        ) : (
          <img
            src={previewUrl}
            alt={attachment.label}
            className="max-h-[75vh] max-w-[80vw] object-contain"
          />
        )}
      </Dialog.Content>
    </Dialog.Root>
  );
}

export function UserMessageAttachments({
  attachments,
}: {
  attachments: UserMessageAttachment[];
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {attachments.map((attachment) =>
        isRasterImageFile(attachment.label) ? (
          <ImageAttachment key={attachment.id} attachment={attachment} />
        ) : (
          <MentionChip
            key={attachment.id}
            icon={<File size={12} />}
            label={attachment.label}
          />
        ),
      )}
    </div>
  );
}
