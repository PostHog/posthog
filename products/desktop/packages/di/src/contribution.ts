import type { ServiceContainer } from "./container";

export interface Contribution {
  start(): void | Promise<void>;
}

export const CONTRIBUTION = Symbol.for("posthog.contribution");

export async function boot(container: ServiceContainer): Promise<void> {
  if (!container.isBound(CONTRIBUTION)) {
    return;
  }

  const contributions = container.getAll(CONTRIBUTION) as Contribution[];

  for (const contribution of contributions) {
    await contribution.start();
  }
}
