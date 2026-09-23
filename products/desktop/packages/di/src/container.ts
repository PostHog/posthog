import type { BindToFluentSyntax, ServiceIdentifier } from "inversify";

export interface ServiceContainer {
  get(serviceIdentifier: ServiceIdentifier): unknown;
  getAll(serviceIdentifier: ServiceIdentifier): unknown[];
  isBound(serviceIdentifier: ServiceIdentifier): boolean;
  bind(serviceIdentifier: ServiceIdentifier): BindToFluentSyntax<unknown>;
}

let rootContainer: ServiceContainer | null = null;
const pendingBindings: Array<(container: ServiceContainer) => void> = [];

export function setRootContainer(container: ServiceContainer): void {
  rootContainer = container;
  for (const bind of pendingBindings) {
    bind(container);
  }
  pendingBindings.length = 0;
}

export function resolveService<T>(serviceIdentifier: ServiceIdentifier<T>): T {
  if (!rootContainer) {
    throw new Error(
      "resolveService called before setRootContainer; the root container is not initialized",
    );
  }

  return rootContainer.get(serviceIdentifier) as T;
}

export function resolveServiceOptional<T>(
  serviceIdentifier: ServiceIdentifier<T>,
): T | null {
  if (!rootContainer || !rootContainer.isBound(serviceIdentifier)) {
    return null;
  }

  return rootContainer.get(serviceIdentifier) as T;
}
