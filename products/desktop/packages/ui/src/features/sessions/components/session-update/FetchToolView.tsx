import { Globe } from "@phosphor-icons/react";
import { Link } from "@radix-ui/themes";
import { ToolRow } from "./ToolRow";
import {
  ContentPre,
  findResourceLink,
  getContentText,
  ToolTitle,
  type ToolViewProps,
  truncateText,
  useToolCallStatus,
} from "./toolCallUtils";

const MAX_URL_LENGTH = 60;

export function FetchToolView({
  toolCall,
  turnCancelled,
  turnComplete,
}: ToolViewProps) {
  const { status, content, title } = toolCall;
  const { isLoading, isFailed, wasCancelled } = useToolCallStatus(
    status,
    turnCancelled,
    turnComplete,
  );

  const resourceLink = findResourceLink(content);
  const fetchedContent = getContentText(content) ?? "";
  const hasContent = fetchedContent.trim().length > 0;

  const url = resourceLink?.uri ?? "";
  const showUrl = url.length > MAX_URL_LENGTH;
  const hasBody = hasContent || showUrl;

  const body = hasBody ? (
    <>
      {showUrl && (
        <div
          className={
            hasContent ? "border-gray-6 border-b px-3 py-2" : "px-3 py-2"
          }
        >
          <Link
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className="break-all text-[13px]"
            onClick={(e) => e.stopPropagation()}
          >
            {url}
          </Link>
        </div>
      )}
      {hasContent && <ContentPre>{fetchedContent}</ContentPre>}
    </>
  ) : undefined;

  return (
    <ToolRow
      icon={Globe}
      isLoading={isLoading}
      isFailed={isFailed}
      wasCancelled={wasCancelled}
      content={body}
    >
      <ToolTitle>{title || "Fetch"}</ToolTitle>
      {url && (
        <ToolTitle>
          <span className="font-mono text-accent-11">
            {truncateText(url, MAX_URL_LENGTH)}
          </span>
        </ToolTitle>
      )}
    </ToolRow>
  );
}
