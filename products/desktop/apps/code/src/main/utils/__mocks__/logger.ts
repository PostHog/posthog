import { vi } from "vitest";

const createScopedLogger = () => ({
  info: vi.fn(),
  warn: vi.fn(),
  error: vi.fn(),
  debug: vi.fn(),
});

export const logger = {
  info: vi.fn(),
  warn: vi.fn(),
  error: vi.fn(),
  debug: vi.fn(),
  scope: () => createScopedLogger(),
};

export type Logger = typeof logger;
export type ScopedLogger = ReturnType<typeof logger.scope>;

export const getLogFilePath = vi.fn(() => "/mock/path/main.log");
