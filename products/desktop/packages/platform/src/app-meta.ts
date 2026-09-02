export interface IAppMeta {
  readonly version: string;
  readonly isProduction: boolean;
  /** Host OS platform (e.g. "darwin", "win32", "linux"). */
  readonly platform: string;
  /** Host CPU arch (e.g. "arm64", "x64"). */
  readonly arch: string;
}

export const APP_META_SERVICE = Symbol.for("posthog.platform.appMeta");
