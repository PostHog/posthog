import { Check, Copy } from "@phosphor-icons/react";
import { Box, Code, IconButton } from "@radix-ui/themes";
import { memo, useCallback, useState } from "react";
import type { Components } from "react-markdown";
import { HighlightedCode } from "../../../../primitives/HighlightedCode";
import { Tooltip } from "../../../../primitives/Tooltip";
import { MarkdownRenderer } from "../../../editor/components/MarkdownRenderer";
import { StreamingMarkdown } from "../../../editor/components/StreamingMarkdown";
import { useSmoothedText } from "../../../editor/components/useSmoothedText";
import {
  BareFileLink,
  hasDirectoryPath,
  InlineFileLink,
  looksLikeBareFilename,
} from "./fileLinkChips";

const agentComponents: Partial<Components> = {
  code: ({ children, className }) => {
    const langMatch = className?.match(/language-(\w+)/);
    if (langMatch) {
      return (
        <HighlightedCode
          code={String(children).replace(/\n$/, "")}
          language={langMatch[1]}
        />
      );
    }

    const text = String(children).replace(/\n$/, "");
    if (hasDirectoryPath(text)) {
      return <InlineFileLink text={text} />;
    }

    const fallback = (
      <Code
        variant="ghost"
        className="border border-border bg-gray-3 text-[13px]"
      >
        {children}
      </Code>
    );

    if (looksLikeBareFilename(text)) {
      return <BareFileLink text={text} fallback={fallback} />;
    }

    return fallback;
  },
};

interface AgentMessageProps {
  content: string;
  /** Active (still-streaming) message: smooth the reveal and block-split the
   *  markdown so each token only re-parses the tail. Completed messages parse
   *  once via MarkdownRenderer for a single, fully-correct render. */
  isStreaming?: boolean;
}

export const AgentMessage = memo(function AgentMessage({
  content,
  isStreaming = false,
}: AgentMessageProps) {
  const [copied, setCopied] = useState(false);
  const smoothed = useSmoothedText(content);

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [content]);

  return (
    <Box className="group/msg relative pl-3 text-[13px] [&>*:last-child]:mb-0 [&_p]:leading-[1.9]">
      {isStreaming ? (
        <StreamingMarkdown
          content={smoothed}
          componentsOverride={agentComponents}
        />
      ) : (
        <MarkdownRenderer
          content={content}
          componentsOverride={agentComponents}
        />
      )}
      <Box className="absolute top-1 left-full ml-2 opacity-0 transition-opacity group-hover/msg:opacity-100">
        <Tooltip content={copied ? "Copied!" : "Copy message"}>
          <IconButton
            size="1"
            variant="ghost"
            color={copied ? "green" : "gray"}
            onClick={handleCopy}
            aria-label="Copy message"
          >
            {copied ? <Check size={14} /> : <Copy size={14} />}
          </IconButton>
        </Tooltip>
      </Box>
    </Box>
  );
});
