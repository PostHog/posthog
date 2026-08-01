import { Check, Code, Copy, Eye } from "@phosphor-icons/react";
import { Flex, IconButton, Text } from "@radix-ui/themes";
import { useState } from "react";
import { Tooltip } from "../../../primitives/Tooltip";

export function DocumentPreviewHeader({
  label,
  content,
  showRendered,
  onToggleRendered,
}: {
  label: string;
  content: string;
  showRendered: boolean;
  onToggleRendered: () => void;
}) {
  const [copied, setCopied] = useState(false);

  const handleCopySource = () => {
    navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Flex
      px="3"
      py="2"
      align="center"
      justify="between"
      className="shrink-0 border-b border-b-(--gray-6)"
    >
      <Text color="gray" className="font-[var(--code-font-family)] text-[13px]">
        {label}
      </Text>
      <Flex align="center" gap="1">
        <Tooltip content={showRendered ? "View source" : "View preview"}>
          <IconButton
            size="1"
            variant="ghost"
            color="gray"
            className="cursor-pointer"
            onClick={onToggleRendered}
            aria-label={showRendered ? "View source" : "View preview"}
          >
            {showRendered ? <Code size={14} /> : <Eye size={14} />}
          </IconButton>
        </Tooltip>
        <Tooltip content={copied ? "Copied" : "Copy source"}>
          <IconButton
            size="1"
            variant="ghost"
            color="gray"
            className="cursor-pointer"
            onClick={handleCopySource}
            aria-label="Copy source"
          >
            {copied ? <Check size={14} /> : <Copy size={14} />}
          </IconButton>
        </Tooltip>
      </Flex>
    </Flex>
  );
}
