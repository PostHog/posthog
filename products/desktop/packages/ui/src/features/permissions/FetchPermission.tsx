import { ActionSelector } from "@posthog/ui/primitives/ActionSelector";
import { Link, Text } from "@radix-ui/themes";
import {
  type BasePermissionProps,
  findTextContent,
  toSelectorOptions,
} from "./types";

function findResourceLink(content: BasePermissionProps["toolCall"]["content"]) {
  const item = content?.find(
    (c) => c.type === "content" && c.content.type === "resource_link",
  );
  if (item?.type === "content" && item.content.type === "resource_link") {
    return item.content;
  }
  return undefined;
}

export function FetchPermission({
  toolCall,
  options,
  onSelect,
  onCancel,
}: BasePermissionProps) {
  const resourceLink = findResourceLink(toolCall.content);
  const textContent = findTextContent(toolCall.content);
  const url = resourceLink?.uri;
  const prompt = resourceLink?.description ?? textContent;
  const isUrl = Boolean(url);

  return (
    <ActionSelector
      title={toolCall.title ?? (isUrl ? "Fetch URL" : "Web search")}
      pendingAction={
        <>
          {url && (
            <Link href={url} target="_blank" className="text-[13px]">
              {url}
            </Link>
          )}
          {prompt && (
            <Text
              color="gray"
              as="p"
              mt={url ? "2" : "0"}
              className="text-[13px]"
            >
              {prompt}
            </Text>
          )}
        </>
      }
      question={
        isUrl
          ? "Do you want to fetch this URL?"
          : "Do you want to run this search?"
      }
      options={toSelectorOptions(options)}
      onSelect={onSelect}
      onCancel={onCancel}
    />
  );
}
