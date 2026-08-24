import { File, Folder, Warning } from "@phosphor-icons/react";
import { unescapeXmlAttr } from "@posthog/shared";
import { Text } from "@radix-ui/themes";
import type { ReactNode } from "react";
import { memo } from "react";
import type { Components } from "react-markdown";
import ReactMarkdown from "react-markdown";
import { GithubRefChip } from "../../../editor/components/GithubRefChip";
import {
  baseComponents,
  defaultRemarkPlugins,
} from "../../../editor/components/MarkdownRenderer";

const MENTION_TAG_REGEX =
  /<file\s+path="([^"]+)"\s*\/>|<(github_issue|github_pr)\s+number="([^"]+)"(?:\s+title="([^"]*)")?(?:\s+url="([^"]*)")?\s*\/>|<error_context\s+label="([^"]*)">[\s\S]*?<\/error_context>|<folder\s+path="([^"]+)"\s*\/>/g;
const MENTION_TAG_TEST =
  /<(?:file\s+path|folder\s+path|github_issue\s+number|github_pr\s+number|error_context\s+label)="[^"]+"/;
const SLASH_COMMAND_START = /^\/([a-zA-Z][\w-]*)(?=\s|$)/;

const inlineComponents: Components = {
  ...baseComponents,
  p: ({ children }) => (
    <Text as="span" color="gray" highContrast className="text-[13px]">
      {children}
    </Text>
  ),
};

export const InlineMarkdown = memo(function InlineMarkdown({
  content,
}: {
  content: string;
}) {
  return (
    <ReactMarkdown
      remarkPlugins={defaultRemarkPlugins}
      components={inlineComponents}
    >
      {content}
    </ReactMarkdown>
  );
});

export function hasMentionTags(content: string): boolean {
  return MENTION_TAG_TEST.test(content) || SLASH_COMMAND_START.test(content);
}

export const hasFileMentions = hasMentionTags;

const chipClass =
  "inline-flex min-w-0 max-w-full items-center gap-1 rounded-[var(--radius-1)] bg-[var(--accent-a3)] px-1 py-px align-middle font-medium text-[var(--accent-11)]";

export function MentionChip({
  icon,
  label,
  onClick,
}: {
  icon: ReactNode;
  label: string;
  onClick?: () => void;
}) {
  const style = { margin: "0 2px" };

  const content = (
    <>
      {icon}
      <span className="truncate">{label}</span>
    </>
  );

  if (onClick) {
    return (
      <button
        type="button"
        className={`${chipClass} cursor-pointer border-none text-[13px]`}
        onClick={onClick}
        style={style}
      >
        {content}
      </button>
    );
  }

  return (
    <span className={`${chipClass} text-[13px]`} style={style}>
      {content}
    </span>
  );
}

export function parseMentionTags(content: string): ReactNode[] {
  const parts: ReactNode[] = [];
  let lastIndex = 0;

  const slashMatch = content.match(SLASH_COMMAND_START);
  if (slashMatch) {
    parts.push(
      <MentionChip key="slash-cmd" icon={null} label={`/${slashMatch[1]}`} />,
    );
    lastIndex = slashMatch[0].length;
  }

  for (const match of content.matchAll(MENTION_TAG_REGEX)) {
    const matchIndex = match.index ?? 0;
    if (matchIndex < lastIndex) continue;

    if (matchIndex > lastIndex) {
      parts.push(
        <InlineMarkdown
          key={`text-${lastIndex}`}
          content={content.slice(lastIndex, matchIndex)}
        />,
      );
    }

    if (match[1]) {
      const filePath = unescapeXmlAttr(match[1]);
      const segments = filePath.split("/").filter(Boolean);
      const fileName = segments.pop() ?? filePath;
      const parentDir = segments.pop();
      const label = parentDir ? `${parentDir}/${fileName}` : fileName;
      parts.push(
        <MentionChip
          key={`file-${matchIndex}`}
          icon={<File size={12} />}
          label={label}
        />,
      );
    } else if (match[2]) {
      const kind = match[2] === "github_pr" ? "pr" : "issue";
      const issueNumber = match[3];
      const issueTitle = match[4] ? unescapeXmlAttr(match[4]) : undefined;
      const issueUrl = match[5] ? unescapeXmlAttr(match[5]) : "";
      const label = issueTitle
        ? `#${issueNumber} - ${issueTitle}`
        : `#${issueNumber}`;
      parts.push(
        <GithubRefChip
          key={`${match[2]}-${matchIndex}`}
          href={issueUrl}
          kind={kind}
        >
          {label}
        </GithubRefChip>,
      );
    } else if (match[6]) {
      parts.push(
        <MentionChip
          key={`error-ctx-${matchIndex}`}
          icon={<Warning size={12} />}
          label={unescapeXmlAttr(match[6])}
        />,
      );
    } else if (match[7]) {
      const folderPath = unescapeXmlAttr(match[7]);
      const segments = folderPath.split("/").filter(Boolean);
      const folderName = segments.pop() ?? folderPath;
      parts.push(
        <MentionChip
          key={`folder-${matchIndex}`}
          icon={<Folder size={12} />}
          label={folderName}
        />,
      );
    }

    lastIndex = matchIndex + match[0].length;
  }

  if (lastIndex < content.length) {
    parts.push(
      <InlineMarkdown
        key={`text-${lastIndex}`}
        content={content.slice(lastIndex)}
      />,
    );
  }

  return parts;
}

export const parseFileMentions = parseMentionTags;
