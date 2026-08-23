export interface FileReadClient {
  readAbsoluteFile(filePath: string): Promise<string | null>;
}

export const FILE_READ_CLIENT = Symbol.for("posthog.core.files.fileReadClient");
