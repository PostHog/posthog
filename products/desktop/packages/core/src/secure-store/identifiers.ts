export interface SecureStoreBackend {
  has(key: string): boolean;
  get(key: string): unknown;
  set(key: string, value: string): void;
  delete(key: string): void;
  clear(): void;
}

export interface SecureStoreLogger {
  info(message: string, ...args: unknown[]): void;
  warn(message: string, ...args: unknown[]): void;
  error(message: string, ...args: unknown[]): void;
  debug(message: string, ...args: unknown[]): void;
}

export const SECURE_STORE_BACKEND = Symbol.for(
  "posthog.core.secureStoreBackend",
);

export const SECURE_STORE_LOGGER = Symbol.for("posthog.core.secureStoreLogger");

export const SECURE_STORE_SERVICE = Symbol.for(
  "posthog.core.secureStoreService",
);
