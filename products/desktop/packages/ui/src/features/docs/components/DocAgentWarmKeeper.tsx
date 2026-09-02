import { useKeepDocAgentWarm } from "../hooks/useKeepDocAgentWarm";

/**
 * Holds the page's warm run.
 *
 * Warming is armed once per mount, so the page remounts this on every use: the
 * request that just took the warm run is also what starts the next one, and the
 * page is never left without a sandbox waiting.
 */
export function DocAgentWarmKeeper() {
  useKeepDocAgentWarm();
  return null;
}
