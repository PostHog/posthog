import { resolve } from "node:path";
import {
  getAgentDir,
  hasTrustRequiringProjectResources,
  ProjectTrustStore,
} from "@earendil-works/pi-coding-agent";

export interface PiProjectTrust {
  trusted: boolean;
  hasProjectResources: boolean;
}

export function readPiProjectTrust(
  projectTrustPath: string,
  runtimeCwd: string = projectTrustPath,
  agentDir: string = getAgentDir(),
): PiProjectTrust {
  return {
    trusted: new ProjectTrustStore(agentDir).get(projectTrustPath) === true,
    hasProjectResources: hasTrustRequiringProjectResources(runtimeCwd),
  };
}

export function writePiProjectTrust(
  projectTrustPath: string,
  trusted: boolean,
  agentDir: string = getAgentDir(),
): void {
  new ProjectTrustStore(agentDir).set(projectTrustPath, trusted);
}

export function createPiProjectTrustResolver(
  initialCwd: string,
  initialTrusted: boolean,
  agentDir: string = getAgentDir(),
): (runtimeCwd: string) => boolean {
  const resolvedInitialCwd = resolve(initialCwd);
  return (runtimeCwd) =>
    resolve(runtimeCwd) === resolvedInitialCwd
      ? initialTrusted
      : readPiProjectTrust(runtimeCwd, runtimeCwd, agentDir).trusted;
}
