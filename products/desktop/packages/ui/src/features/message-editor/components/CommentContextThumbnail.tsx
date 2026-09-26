import { ChatCircleTextIcon } from "@phosphor-icons/react";
import { cn } from "@posthog/quill";
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
        "relative inline-block h-3.5 w-5 overflow-hidden rounded-[3px] bg-white align-middle ring-1 ring-current/25",
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
