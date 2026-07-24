export interface FileReadClient {
  readAbsoluteFile(filePath: string): Promise<string | null>;
}

export interface TitleGeneratorLogger {
  error(message: string, data?: unknown): void;
}

export const TITLE_GENERATOR_SERVICE = Symbol.for(
  "posthog.core.sessions.titleGeneratorService",
);
export const TITLE_GENERATOR_FILE_READ_CLIENT = Symbol.for(
  "posthog.core.sessions.titleGeneratorFileReadClient",
);
export const TITLE_GENERATOR_LOGGER = Symbol.for(
  "posthog.core.sessions.titleGeneratorLogger",
);
