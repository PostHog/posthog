import { useMemo } from "react";
import { ScrollView, Text, View } from "react-native";
import { getCloudUrlFromRegion, useAuthStore } from "@/features/auth";
import { UNIVERSAL_LINK_PREFIX } from "@/lib/deep-links";
import { parseGithubIssueUrl } from "@/lib/githubIssueUrl";
import { openExternalUrl } from "@/lib/openExternalUrl";
import { type ParsePostHogUrlOptions, parsePostHogUrl } from "@/lib/posthogUrl";
import { getColorForClass, highlightCode } from "@/lib/syntax-highlight";
import { useThemeColors } from "@/lib/theme";
import { CopyButton } from "./CopyButton";
import { GithubRefChip } from "./GithubRefChip";
import { MarkdownImage } from "./MarkdownImage";
import { PostHogRefChip } from "./PostHogRefChip";

const IMAGE_LINE_PATTERN = /^!\[([^\]]*)\]\(([^)\s]+)\)\s*$/;
const BARE_POSTHOG_REF_PATTERN =
  /(https?:\/\/(?:app\.posthog\.com|(?:us|eu)\.posthog\.com|code\.posthog\.com|(?:www\.)?posthog\.com|localhost(?::\d+)?)\/[^\s<>()\]]+|\/(?:insights|project|organization|settings|feature_flags|experiments|dashboard|dashboards|replay|session_replay|recordings|error_tracking|task|inbox|automation)\b[^\s<>()\]]*)/g;

interface MarkdownTextProps {
  content: string;
}

function HighlightedCode({
  code,
  language,
}: {
  code: string;
  language: string;
}) {
  const themeColors = useThemeColors();
  const segments = useMemo(
    () => highlightCode(code, language),
    [code, language],
  );

  if (!segments) {
    return (
      <Text className="font-mono text-[12px] text-gray-12 leading-4" selectable>
        {code}
      </Text>
    );
  }

  return (
    <Text className="font-mono text-[12px] leading-4" selectable>
      {segments.map((segment, i) => (
        <Text
          key={`s-${i}-${segment.className ?? "p"}`}
          style={{
            color: getColorForClass(segment.className) ?? themeColors.gray[12],
          }}
        >
          {segment.text}
        </Text>
      ))}
    </Text>
  );
}

interface Block {
  type:
    | "paragraph"
    | "code"
    | "heading"
    | "list"
    | "table"
    | "blockquote"
    | "image"
    | "hr";
  content: string;
  language?: string;
  level?: number;
  items?: string[];
  ordered?: boolean;
  rows?: string[][];
  url?: string;
  alt?: string;
}

function parseBlocks(text: string): Block[] {
  const lines = text.split("\n");
  const blocks: Block[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Code block
    if (line.startsWith("```")) {
      const language = line.slice(3).trim() || undefined;
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      i++; // skip closing ```
      blocks.push({ type: "code", content: codeLines.join("\n"), language });
      continue;
    }

    // Image on its own line: ![alt](url)
    const imageMatch = line.match(IMAGE_LINE_PATTERN);
    if (imageMatch) {
      blocks.push({
        type: "image",
        content: "",
        alt: imageMatch[1],
        url: imageMatch[2],
      });
      i++;
      continue;
    }

    // Heading
    const headingMatch = line.match(/^(#{1,6})\s+(.+)$/);
    if (headingMatch) {
      blocks.push({
        type: "heading",
        content: headingMatch[2],
        level: headingMatch[1].length,
      });
      i++;
      continue;
    }

    // Horizontal rule (---, ***, ___ with optional spaces, 3+ chars)
    if (/^([-*_])\s*\1\s*\1[\s1]*$/.test(line)) {
      blocks.push({ type: "hr", content: "" });
      i++;
      continue;
    }

    // Blockquote (consecutive > lines)
    if (/^>\s?/.test(line)) {
      const quoteLines: string[] = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) {
        quoteLines.push(lines[i].replace(/^>\s?/, ""));
        i++;
      }
      blocks.push({ type: "blockquote", content: quoteLines.join("\n") });
      continue;
    }

    // Unordered list (consecutive - or * lines)
    if (/^\s*[-*]\s/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*]\s/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*]\s+/, ""));
        i++;
      }
      blocks.push({ type: "list", content: "", items });
      continue;
    }

    // Ordered list (consecutive 1. 2. lines)
    if (/^\s*\d+[.)]\s/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*\d+[.)]\s/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*\d+[.)]\s+/, ""));
        i++;
      }
      blocks.push({ type: "list", content: "", items, ordered: true });
      continue;
    }

    // Table: lines with pipes, second line is separator (|---|---|)
    if (
      line.includes("|") &&
      i + 1 < lines.length &&
      /^\s*\|?[\s-:|]+\|/.test(lines[i + 1])
    ) {
      const rows: string[][] = [];
      while (i < lines.length && lines[i].includes("|")) {
        const row = lines[i]
          .replace(/^\s*\|/, "")
          .replace(/\|\s*$/, "")
          .split("|")
          .map((cell) => cell.trim());
        // Skip the separator row
        if (!/^[\s-:|]+$/.test(lines[i].replace(/\|/g, ""))) {
          rows.push(row);
        }
        i++;
      }
      if (rows.length > 0) {
        blocks.push({ type: "table", content: "", rows });
      }
      continue;
    }

    // Empty line
    if (line.trim() === "") {
      i++;
      continue;
    }

    // Paragraph: collect consecutive non-special lines
    const paraLines: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !lines[i].startsWith("```") &&
      !lines[i].match(/^#{1,6}\s/) &&
      !IMAGE_LINE_PATTERN.test(lines[i]) &&
      !/^\s*[-*]\s/.test(lines[i]) &&
      !/^\s*\d+[.)]\s/.test(lines[i]) &&
      !/^>\s?/.test(lines[i]) &&
      !/^([-*_])\s*\1\s*\1[\s1]*$/.test(lines[i]) &&
      !(
        lines[i].includes("|") &&
        i + 1 < lines.length &&
        /^\s*\|?[\s-:|]+\|/.test(lines[i + 1])
      )
    ) {
      paraLines.push(lines[i]);
      i++;
    }
    if (paraLines.length > 0) {
      blocks.push({ type: "paragraph", content: paraLines.join("\n") });
    }
  }

  return blocks;
}

function openUrl(url: string) {
  openExternalUrl(url);
}

function splitTrailingPunctuation(text: string): {
  reference: string;
  trailing: string;
} {
  const reference = text.replace(/[.,!?;:]+$/u, "");
  return {
    reference,
    trailing: text.slice(reference.length),
  };
}

function renderPlainText(
  text: string,
  posthogUrlOptions: ParsePostHogUrlOptions,
  keyBase: string,
): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null = null;

  BARE_POSTHOG_REF_PATTERN.lastIndex = 0;

  // biome-ignore lint/suspicious/noAssignInExpressions: regex exec loop
  while ((match = BARE_POSTHOG_REF_PATTERN.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index));
    }

    const candidate = match[0];
    const { reference, trailing } = splitTrailingPunctuation(candidate);
    const posthogRef = parsePostHogUrl(reference, posthogUrlOptions);

    if (posthogRef) {
      nodes.push(
        <PostHogRefChip
          key={`${keyBase}-${match.index}`}
          href={posthogRef.normalizedUrl}
          kind={posthogRef.kind}
          label={posthogRef.defaultLabel}
        />,
      );

      if (trailing) {
        nodes.push(trailing);
      }
    } else {
      nodes.push(candidate);
    }

    lastIndex = match.index + candidate.length;
  }

  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }

  return nodes.length > 0 ? nodes : [text];
}

function formatPostHogChipLabel(
  posthogRef: ReturnType<typeof parsePostHogUrl>,
  linkText: string,
  url: string,
): string {
  if (!posthogRef) return linkText;
  if (linkText === url) return posthogRef.defaultLabel;

  const normalizedLinkText = linkText.trim();
  if (!posthogRef.refId) return normalizedLinkText;
  if (normalizedLinkText.endsWith(`(${posthogRef.refId})`)) {
    return normalizedLinkText;
  }

  return `${normalizedLinkText} (${posthogRef.refId})`;
}

function renderInline(
  text: string,
  posthogUrlOptions: ParsePostHogUrlOptions,
): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  // Links must come first to avoid bold/italic consuming text inside [].
  // Order after links: strikethrough, bold, italic, inline code.
  const pattern =
    /(\[([^\]]+)\]\(([^)]+)\)|~~(.+?)~~|\*\*(.+?)\*\*|\*(.+?)\*|`([^`]+)`)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null = null;

  // biome-ignore lint/suspicious/noAssignInExpressions: regex exec loop
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(
        ...renderPlainText(
          text.slice(lastIndex, match.index),
          posthogUrlOptions,
          `plain-${match.index}`,
        ),
      );
    }

    if (match[2] && match[3]) {
      // Link: [text](url)
      const linkText = match[2];
      const url = match[3];
      const githubRef = parseGithubIssueUrl(url);
      if (githubRef) {
        const isAutoLink = linkText === url;
        const label = isAutoLink
          ? `${githubRef.owner}/${githubRef.repo}#${githubRef.number}`
          : linkText;
        nodes.push(
          <GithubRefChip
            key={match.index}
            href={githubRef.normalizedUrl}
            kind={githubRef.kind}
            label={label}
          />,
        );
      } else {
        const posthogRef = parsePostHogUrl(url, posthogUrlOptions);
        if (posthogRef) {
          nodes.push(
            <PostHogRefChip
              key={match.index}
              href={posthogRef.normalizedUrl}
              kind={posthogRef.kind}
              label={formatPostHogChipLabel(posthogRef, linkText, url)}
            />,
          );
        } else {
          nodes.push(
            <Text
              key={match.index}
              className="text-accent-11 underline"
              onPress={() => openUrl(url)}
            >
              {linkText}
              <Text className="text-accent-11">{" ↗"}</Text>
            </Text>,
          );
        }
      }
    } else if (match[4]) {
      // Strikethrough: ~~text~~
      nodes.push(
        <Text key={match.index} className="text-gray-9 line-through">
          {match[4]}
        </Text>,
      );
    } else if (match[5]) {
      // Bold
      nodes.push(
        <Text key={match.index} className="font-bold text-accent-11">
          {match[5]}
        </Text>,
      );
    } else if (match[6]) {
      // Italic
      nodes.push(
        <Text key={match.index} className="italic">
          {match[6]}
        </Text>,
      );
    } else if (match[7]) {
      // Inline code
      nodes.push(
        <Text
          key={match.index}
          className="rounded bg-gray-4 px-1 font-mono text-[12px] text-accent-11"
        >
          {match[7]}
        </Text>,
      );
    }

    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < text.length) {
    nodes.push(
      ...renderPlainText(
        text.slice(lastIndex),
        posthogUrlOptions,
        `plain-tail-${lastIndex}`,
      ),
    );
  }

  return nodes.length > 0 ? nodes : [text];
}

export function MarkdownText({ content }: MarkdownTextProps) {
  const blocks = parseBlocks(content);
  const cloudRegion = useAuthStore((state) => state.cloudRegion);
  const posthogUrlOptions = useMemo<ParsePostHogUrlOptions>(
    () => ({
      appBaseUrl: cloudRegion ? getCloudUrlFromRegion(cloudRegion) : null,
      codeBaseUrl: UNIVERSAL_LINK_PREFIX,
    }),
    [cloudRegion],
  );

  return (
    <View style={{ gap: 8 }}>
      {blocks.map((block, i) => {
        const key = `block-${i}`;

        switch (block.type) {
          case "code":
            return (
              <View
                key={key}
                className="rounded-md border border-gray-6 bg-gray-3"
              >
                <View className="flex-row items-center justify-between border-gray-6 border-b px-3 py-1">
                  <Text className="font-mono text-[10px] text-gray-9">
                    {block.language}
                  </Text>
                  <CopyButton
                    text={block.content}
                    size={13}
                    label="Copy code"
                  />
                </View>
                <View className="px-3 py-2">
                  {block.language ? (
                    <HighlightedCode
                      code={block.content}
                      language={block.language}
                    />
                  ) : (
                    <Text
                      className="font-mono text-[12px] text-gray-12 leading-4"
                      selectable
                    >
                      {block.content}
                    </Text>
                  )}
                </View>
              </View>
            );

          case "heading":
            return (
              <Text
                key={key}
                className={`font-bold text-accent-11 ${
                  block.level === 1
                    ? "text-[16px]"
                    : block.level === 2
                      ? "text-[14px]"
                      : "text-[13px]"
                }`}
              >
                {renderInline(block.content, posthogUrlOptions)}
              </Text>
            );

          case "list":
            return (
              <View key={key} style={{ gap: 4 }}>
                {block.items?.map((item, idx) => {
                  const taskMatch = !block.ordered
                    ? item.match(/^\[([ xX])\]\s+(.*)$/)
                    : null;
                  const isTask = taskMatch !== null;
                  const isChecked = isTask && /[xX]/.test(taskMatch[1]);
                  const itemText = isTask ? taskMatch[2] : item;
                  return (
                    <View
                      key={`${key}-${idx}-${item}`}
                      className="flex-row items-start pl-2"
                    >
                      {isTask ? (
                        <Text
                          className={`mr-2 font-mono text-[13px] ${
                            isChecked ? "text-accent-11" : "text-gray-9"
                          }`}
                        >
                          {isChecked ? "☑" : "☐"}
                        </Text>
                      ) : (
                        <Text className="mr-2 text-[13px] text-gray-9">
                          {block.ordered ? `${idx + 1}.` : "•"}
                        </Text>
                      )}
                      <Text
                        className={`flex-1 text-[13px] leading-5 ${
                          isTask && isChecked
                            ? "text-gray-10 line-through"
                            : "text-gray-12"
                        }`}
                      >
                        {renderInline(itemText, posthogUrlOptions)}
                      </Text>
                    </View>
                  );
                })}
              </View>
            );

          case "table": {
            const rows = block.rows ?? [];
            const header = rows[0];
            const body = rows.slice(1);
            return (
              <ScrollView
                key={key}
                horizontal
                showsHorizontalScrollIndicator={false}
              >
                <View className="overflow-hidden rounded-md border border-gray-6">
                  {header && (
                    <View className="flex-row bg-gray-3">
                      {header.map((cell, col) => {
                        const colKey = `${key}-h${col}-${cell}`;
                        return (
                          <View
                            key={colKey}
                            className="border-gray-6 px-3 py-1.5"
                            style={
                              col > 0
                                ? {
                                    borderLeftWidth: 1,
                                    borderLeftColor: "#3333",
                                  }
                                : undefined
                            }
                          >
                            <Text className="font-bold text-[12px] text-gray-12">
                              {renderInline(cell, posthogUrlOptions)}
                            </Text>
                          </View>
                        );
                      })}
                    </View>
                  )}
                  {body.map((row, ri) => {
                    const rowKey = `${key}-r${ri}`;
                    return (
                      <View
                        key={rowKey}
                        className="flex-row border-gray-6 border-t"
                      >
                        {row.map((cell, col) => {
                          const cellKey = `${rowKey}-c${col}-${cell}`;
                          return (
                            <View
                              key={cellKey}
                              className="px-3 py-1.5"
                              style={
                                col > 0
                                  ? {
                                      borderLeftWidth: 1,
                                      borderLeftColor: "#3333",
                                    }
                                  : undefined
                              }
                            >
                              <Text className="text-[12px] text-gray-12">
                                {renderInline(cell, posthogUrlOptions)}
                              </Text>
                            </View>
                          );
                        })}
                      </View>
                    );
                  })}
                </View>
              </ScrollView>
            );
          }

          case "blockquote":
            return (
              <View key={key} className="border-accent-6 border-l-2 pl-3">
                <Text className="text-[13px] text-gray-11 italic leading-5">
                  {renderInline(block.content, posthogUrlOptions)}
                </Text>
              </View>
            );

          case "image":
            return block.url ? (
              <MarkdownImage key={key} url={block.url} alt={block.alt} />
            ) : null;

          case "hr":
            return <View key={key} className="my-1 h-px bg-gray-6" />;

          default:
            return (
              <Text key={key} className="text-[13px] text-gray-12 leading-5">
                {renderInline(block.content, posthogUrlOptions)}
              </Text>
            );
        }
      })}
    </View>
  );
}
