const ARTIFACT_DOWNLOAD =
  /^\/api\/projects\/(\d+)\/tasks\/([^/]+)\/runs\/([^/]+)\/artifacts\/([^/]+)\/download\/?$/;

export function artifactDownloadPath(uri: string): RegExpExecArray | null {
  try {
    return ARTIFACT_DOWNLOAD.exec(
      new URL(uri, "https://example.invalid").pathname,
    );
  } catch {
    return null;
  }
}

export function imageArtifactReference(
  uri: string,
  host: string,
  projectId: number,
): {
  taskId: string;
  runId: string;
  artifactId: string;
} | null {
  try {
    const url = new URL(uri, host);
    const match = ARTIFACT_DOWNLOAD.exec(url.pathname);
    if (
      !match ||
      url.origin !== new URL(host).origin ||
      url.username ||
      url.password ||
      Number(match[1]) !== projectId
    )
      return null;
    return { taskId: match[2], runId: match[3], artifactId: match[4] };
  } catch {
    return null;
  }
}
