import { readFile, realpath, stat } from "node:fs/promises";
import { isAbsolute, relative, resolve } from "node:path";

const MAX_FILE_BYTES = 2_000_000;

export async function readWorkspaceFile(
  filePath: string,
  repositoryPath: string,
): Promise<{ content: string }> {
  const root = await realpath(repositoryPath);
  const requestedPath = isAbsolute(filePath)
    ? filePath
    : resolve(root, filePath);
  const resolvedPath = await realpath(requestedPath);
  const relativePath = relative(root, resolvedPath);

  if (relativePath.startsWith("..") || isAbsolute(relativePath)) {
    throw new Error("File is outside the repository");
  }

  const fileStat = await stat(resolvedPath);
  if (!fileStat.isFile()) {
    throw new Error("Path is not a file");
  }
  if (fileStat.size > MAX_FILE_BYTES) {
    throw new Error("File is too large to preview");
  }

  return { content: await readFile(resolvedPath, "utf8") };
}
