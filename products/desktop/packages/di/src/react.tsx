import type { ServiceIdentifier } from "inversify";
import type { ReactNode } from "react";
import { createContext, useContext, useMemo } from "react";
import type { ServiceContainer } from "./container";

const ServiceContext = createContext<ServiceContainer | null>(null);

export function ServiceProvider({
  children,
  container,
}: {
  children: ReactNode;
  container: ServiceContainer;
}) {
  const value = useMemo(() => container, [container]);

  return (
    <ServiceContext.Provider value={value}>{children}</ServiceContext.Provider>
  );
}

export function useService<T>(serviceIdentifier: ServiceIdentifier<T>): T {
  const container = useContext(ServiceContext);
  if (!container) {
    throw new Error("useService must be used within a ServiceProvider");
  }

  return container.get(serviceIdentifier) as T;
}

export function useServiceOptional<T>(
  serviceIdentifier: ServiceIdentifier<T>,
): T | null {
  const container = useContext(ServiceContext);
  if (!container) {
    throw new Error("useServiceOptional must be used within a ServiceProvider");
  }

  if (!container.isBound(serviceIdentifier)) {
    return null;
  }

  return container.get(serviceIdentifier) as T;
}
