import type { CustomCloud } from "@posthog/shared";

export const CUSTOM_CLOUD_STORE = Symbol.for("posthog.core.customCloudStore");

export interface CustomCloudStore {
  get(): CustomCloud | null;
  set(target: CustomCloud | null): CustomCloud | null;
}
