import type { ContentBlock } from "@agentclientprotocol/sdk";
import {
  CLOUD_PROMPT_PREFIX,
  estimateBase64Bytes,
  getFileExtension,
  getFileName,
  getImageMimeType,
  isAbsolutePath,
  isClaudeImageFile,
  isRasterImageFile,
  MAX_CLAUDE_IMAGE_BYTES,
  pathToFileUri,
  serializeCloudPrompt,
  unescapeXmlAttr,
} from "@posthog/shared";
import { skillTagsToSlashCommands } from "../message-editor/skillTags";

export type ReadFileAsBase64 = (filePath: string) => Promise<string | null>;

const ABSOLUTE_FILE_TAG_REGEX = /<file\s+path="([^"]+)"\s*\/>/g;
const FOLDER_TAG_REGEX = /<folder\s+path="[^"]+"\s*\/>/g;
const FOLDER_TAG_PATH_REGEX = /<folder\s+path="([^"]+)"\s*\/>/g;
const TEXT_EXTENSIONS = new Set([
  "c",
  "cc",
  "cfg",
  "conf",
  "cpp",
  "cs",
  "css",
  "csv",
  "env",
  "gitignore",
  "go",
  "h",
  "hpp",
  "html",
  "ini",
  "java",
  "js",
  "json",
  "jsx",
  "log",
  "md",
  "mjs",
  "py",
  "rb",
  "rs",
  "scss",
  "sh",
  "sql",
  "svg",
  "toml",
  "ts",
  "tsx",
  "txt",
  "xml",
  "yaml",
  "yml",
  "zsh",
]);
const TEXT_FILENAMES = new Set([
  ".env",
  ".gitignore",
  "Dockerfile",
  "LICENSE",
  "Makefile",
  "README",
  "README.md",
]);
function isTextAttachment(filePath: string): boolean {
  const fileName = getFileName(filePath);
  const ext = getFileExtension(filePath);
  return TEXT_FILENAMES.has(fileName) || TEXT_EXTENSIONS.has(ext);
}

export function isSupportedCloudTextAttachment(filePath: string): boolean {
  return isTextAttachment(filePath);
}

function collectAbsoluteFileTagPaths(prompt: string): string[] {
  const filePaths: string[] = [];

  for (const match of prompt.matchAll(ABSOLUTE_FILE_TAG_REGEX)) {
    const decodedPath = unescapeXmlAttr(match[1]);
    if (isAbsolutePath(decodedPath)) {
      filePaths.push(decodedPath);
    }
  }

  return filePaths;
}

function collectFolderTagPaths(prompt: string): Set<string> {
  const paths = new Set<string>();
  for (const match of prompt.matchAll(FOLDER_TAG_PATH_REGEX)) {
    paths.add(unescapeXmlAttr(match[1]));
  }
  return paths;
}

function unique<T>(values: T[]): T[] {
  return Array.from(new Set(values));
}

function normalizePromptText(prompt: string): string {
  return prompt.replace(/\n{3,}/g, "\n\n").trim();
}

export function stripSkillTags(prompt: string): string {
  return skillTagsToSlashCommands(prompt);
}

export function stripAttachmentTags(prompt: string): string {
  return normalizePromptText(
    prompt
      .replaceAll(ABSOLUTE_FILE_TAG_REGEX, (match, rawPath: string) => {
        const decodedPath = unescapeXmlAttr(rawPath);
        return isAbsolutePath(decodedPath) ? "" : match;
      })
      .replaceAll(FOLDER_TAG_REGEX, ""),
  );
}

export function stripAbsoluteFileTags(prompt: string): string {
  return stripSkillTags(stripAttachmentTags(prompt));
}

export function getAbsoluteAttachmentPaths(
  prompt: string,
  filePaths: string[] = [],
): string[] {
  const normalize = (p: string) => p.replaceAll("\\", "/");
  const folderPaths = collectFolderTagPaths(prompt);
  const normalizedFolderPaths = new Set(Array.from(folderPaths, normalize));
  const absolutePaths = [
    ...collectAbsoluteFileTagPaths(prompt),
    ...filePaths.filter(isAbsolutePath),
  ];
  return unique(absolutePaths).filter(
    (p) => !normalizedFolderPaths.has(normalize(p)),
  );
}

export const ATTACHMENT_SUMMARY_PREFIX = "Attached files: ";
const TRAILING_ATTACHMENT_SUMMARY_REGEX = new RegExp(
  `(?:^|\\n)${ATTACHMENT_SUMMARY_PREFIX}[^\\n]*$`,
);

export function stripTrailingAttachmentSummary(text: string): string {
  return text.replace(TRAILING_ATTACHMENT_SUMMARY_REGEX, "").trim();
}

export function buildCloudTaskDescription(
  prompt: string,
  filePaths: string[] = [],
): string {
  const strippedPrompt = stripAbsoluteFileTags(prompt);
  const attachmentNames = getAbsoluteAttachmentPaths(prompt, filePaths).map(
    getFileName,
  );

  if (attachmentNames.length === 0) {
    return strippedPrompt;
  }

  const attachmentSummary = `${ATTACHMENT_SUMMARY_PREFIX}${attachmentNames.join(", ")}`;
  return strippedPrompt
    ? `${strippedPrompt}\n\n${attachmentSummary}`
    : attachmentSummary;
}

async function buildAttachmentBlock(
  filePath: string,
  readFileAsBase64: ReadFileAsBase64,
): Promise<ContentBlock> {
  const fileName = getFileName(filePath);
  const uri = pathToFileUri(filePath);

  if (isClaudeImageFile(fileName)) {
    const base64 = await readFileAsBase64(filePath);
    if (!base64) {
      throw new Error(`Unable to read attached image ${fileName}`);
    }

    if (estimateBase64Bytes(base64) > MAX_CLAUDE_IMAGE_BYTES) {
      throw new Error(
        `${fileName} is too large for a cloud image attachment (max 5 MB)`,
      );
    }

    return {
      type: "image",
      data: base64,
      mimeType: getImageMimeType(fileName),
      uri,
    };
  }

  if (isRasterImageFile(fileName)) {
    throw new Error(
      `Cloud image attachments currently support PNG, JPG, GIF, and WebP. Unsupported image: ${fileName}`,
    );
  }

  if (!isTextAttachment(fileName)) {
    throw new Error(
      `Cloud attachments currently support text and image files. Unsupported attachment: ${fileName}`,
    );
  }

  return {
    type: "resource_link",
    uri,
    name: fileName,
  };
}

export async function buildCloudPromptBlocks(
  prompt: string,
  filePaths: string[] = [],
  readFileAsBase64: ReadFileAsBase64,
): Promise<ContentBlock[]> {
  const promptText = stripAbsoluteFileTags(prompt);
  const attachmentPaths = getAbsoluteAttachmentPaths(prompt, filePaths);

  const attachmentBlocks = await Promise.all(
    attachmentPaths.map((filePath) =>
      buildAttachmentBlock(filePath, readFileAsBase64),
    ),
  );

  const blocks: ContentBlock[] = [];
  if (promptText) {
    blocks.push({ type: "text", text: promptText });
  }
  blocks.push(...attachmentBlocks);

  if (blocks.length === 0) {
    throw new Error("Cloud prompt cannot be empty");
  }

  return blocks;
}

export { CLOUD_PROMPT_PREFIX, serializeCloudPrompt };
