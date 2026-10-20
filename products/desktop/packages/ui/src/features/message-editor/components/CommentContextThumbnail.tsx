import { ChatCircleTextIcon } from "@phosphor-icons/react";
import { cn } from "@posthog/quill";
import { WEB_PAGE_BACKGROUND } from "@posthog/ui/features/task-preview/pageBackground";
import { useLocalImage } from "./useLocalImage";

export function CommentContextThumbnail({
  imagePath,
  className,
}: {
  imagePath?: string;
  className?: string;
}) {
  const image = useLocalImage(imagePath);
  if (!image) {
    return <ChatCircleTextIcon size={12} className={className} />;
  }
  return (
    <span
      className={cn(
        "relative inline-block h-3.5 w-5 overflow-hidden rounded-[3px] align-middle ring-1 ring-current/25",
        WEB_PAGE_BACKGROUND,
        className,
      )}
    >
      <img
        src={image}
        alt=""
        className="absolute inset-0 size-full scale-[2.2] object-cover"
      />
    </span>
  );
}
