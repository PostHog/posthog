import type { HomeWork, HomeWorkInput } from "./homeSchemas";

// The method surface the host-router home router depends on. The concrete
// implementation binds to HOME_SERVICE in home.module.ts.
export interface IHomeService {
  work(input: HomeWorkInput): Promise<HomeWork>;
}
