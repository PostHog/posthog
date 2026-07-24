import type { ServiceIdentifier } from "inversify";

export interface ServiceResolver {
  get<T>(serviceIdentifier: ServiceIdentifier<T>): T;
}

export interface HostContext {
  container: ServiceResolver;
}
