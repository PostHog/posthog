export interface DetectorLogger {
  warn(message: string, ...args: unknown[]): void;
}

const noop: DetectorLogger = {
  warn() {},
};

let current: DetectorLogger = noop;

export function setLogger(logger: DetectorLogger): void {
  current = logger;
}

export function warn(message: string, ...args: unknown[]): void {
  current.warn(message, ...args);
}
