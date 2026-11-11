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

// Preserve the validated trust decision only for the CWD that started this
// runtime. A replacement runtime with another CWD must resolve its own trust.
export function createPiRuntimeTrustResolver(
  trustedRuntimeCwd: string,
  trusted: boolean,
  agentDir: string = getAgentDir(),
): (runtimeCwd: string) => boolean {
  const resolvedTrustedRuntimeCwd = resolve(trustedRuntimeCwd);

  return (runtimeCwd) => {
    if (resolve(runtimeCwd) === resolvedTrustedRuntimeCwd) {
      return trusted;
    }

    return readPiProjectTrust(runtimeCwd, runtimeCwd, agentDir).trusted;
  };
}
