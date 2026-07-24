export interface FileSourceInput {
  isInsideRepo: boolean;
  isCloudRun: boolean;
  isImage: boolean;
}

export interface FileSourceFlags {
  cloudEnabled: boolean;
  repoEnabled: boolean;
  absoluteEnabled: boolean;
  imageEnabled: boolean;
}

export function selectFileSource({
  isInsideRepo,
  isCloudRun,
  isImage,
}: FileSourceInput): FileSourceFlags {
  return {
    cloudEnabled: isCloudRun && !isImage,
    repoEnabled: isInsideRepo && !isImage && !isCloudRun,
    absoluteEnabled: !isInsideRepo && !isImage && !isCloudRun,
    imageEnabled: isImage && !isCloudRun,
  };
}

export interface CloudFileState {
  content: string | null | undefined;
  isLoading: boolean;
}

export interface LocalQueryState {
  content: string | null | undefined;
  isLoading: boolean;
  error: unknown;
}

export interface CollapsedFileState {
  content: string | null | undefined;
  isLoading: boolean;
  error: unknown;
}

export function collapseFileState({
  cloudFile,
  localQuery,
  isCloudRun,
}: {
  cloudFile: CloudFileState;
  localQuery: LocalQueryState;
  isCloudRun: boolean;
}): CollapsedFileState {
  if (isCloudRun) {
    return {
      content: cloudFile.content,
      isLoading: cloudFile.isLoading,
      error: null,
    };
  }
  return {
    content: localQuery.content,
    isLoading: localQuery.isLoading,
    error: localQuery.error,
  };
}

export interface ResolvedMarkdownLink {
  kind: "external" | "internal";
  href: string;
  relativePath: string | null;
  absolutePath: string | null;
}

export function resolveMarkdownLink(
  href: string,
  filePath: string,
  repoPath: string | null | undefined,
): ResolvedMarkdownLink {
  if (href.startsWith("http://") || href.startsWith("https://")) {
    return { kind: "external", href, relativePath: null, absolutePath: null };
  }
  const cleanHref = href.replace(/^\.\//, "");
  const dir = filePath.includes("/")
    ? filePath.slice(0, filePath.lastIndexOf("/"))
    : "";
  const resolved = dir ? `${dir}/${cleanHref}` : cleanHref;
  return {
    kind: "internal",
    href,
    relativePath: resolved,
    absolutePath: repoPath ? `${repoPath}/${resolved}` : null,
  };
}
