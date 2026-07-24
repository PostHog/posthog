import type { ServiceIdentifier } from "inversify";
import type { ServiceContainer } from "./container";

/**
 * A DI token that shared `@posthog/ui` / `@posthog/core` resolves via service
 * location (`useService` / `resolveService`) and that every host mounting the
 * shared app must therefore bind in its composition root.
 */
export interface HostCapabilityRequirement {
  /** The token the shared app resolves at runtime. */
  readonly token: ServiceIdentifier;
  /** What breaks when it's missing — surfaced in the error message. */
  readonly description: string;
}

/**
 * Throw if the host forgot to bind a capability the shared app resolves at
 * runtime.
 *
 * These gaps are invisible to the compiler: `useService<T>(TOKEN)`'s type
 * argument is supplied by the caller, not derived from any host's binding map,
 * so a `TypedContainer<HostBindings>` only checks the *provider* side. A missing
 * binding otherwise surfaces only when a user reaches the code path that
 * resolves the token (as happened with the inbox `reportModelResolver` on web).
 *
 * Call this synchronously at the end of each composition root, once every
 * binding is registered, so a broken container fails to start instead of
 * limping to the first unlucky navigation.
 */
export function assertHostCapabilities(
  container: Pick<ServiceContainer, "isBound">,
  requirements: readonly HostCapabilityRequirement[],
): void {
  const missing = requirements.filter((r) => !container.isBound(r.token));
  if (missing.length === 0) {
    return;
  }

  const lines = missing.map((r) => `  - ${String(r.token)}: ${r.description}`);
  throw new Error(
    `Host container is missing ${missing.length} required capability ` +
      `binding(s) that shared UI/core resolves at runtime:\n${lines.join("\n")}\n` +
      "Bind them in this host's composition root. See REQUIRED_HOST_CAPABILITIES " +
      "in @posthog/ui/shell/requiredHostCapabilities.",
  );
}
