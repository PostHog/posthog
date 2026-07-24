export interface IBundledResources {
  /**
   * Resolve a bundled resource (code, asset) to an absolute path on disk.
   * On desktop this handles ASAR .unpacked resolution; on server this points
   * to the app install directory; on mobile this resolves under the app bundle.
   */
  resolve(relativePath: string): string;
}

export const BUNDLED_RESOURCES_SERVICE = Symbol.for(
  "posthog.platform.bundledResources",
);
