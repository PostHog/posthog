export interface IFileIcon {
  /**
   * Return the icon for a file (typically an application bundle) as a data URL.
   * Returns null on hosts that cannot resolve OS-level file icons (web, mobile).
   */
  getAsDataUrl(filePath: string): Promise<string | null>;
}

export const FILE_ICON_SERVICE = Symbol.for("posthog.platform.fileIcon");
