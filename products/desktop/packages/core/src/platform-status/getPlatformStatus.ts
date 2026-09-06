import type { CloudRegion } from "@posthog/shared";
import type { PlatformStatus } from "./platformStatusStore";

const STATUS_API_URL = "https://www.posthogstatus.com/api/status";
const STATUS_PAGE_URLS = {
  us: "https://www.posthogstatus.com/us",
  eu: "https://www.posthogstatus.com/eu",
} as const;
const DESKTOP_COMPONENT_NAMES = new Set(["App", "PostHog Desktop"]);
const STATUS_PRIORITY = {
  operational: 0,
  degraded_performance: 1,
  partial_outage: 2,
  major_outage: 3,
} as const;

type KnownStatus = keyof typeof STATUS_PRIORITY;
type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;
type StatusComponent = {
  name?: unknown;
  status?: unknown;
};
type StatusGroup = {
  name?: unknown;
  components?: unknown[];
};
type StatusResponse = {
  component_groups: unknown[];
};

export async function getPlatformStatus(
  region: CloudRegion,
  fetcher: Fetcher = fetch,
): Promise<PlatformStatus> {
  const resolvedRegion = region === "eu" ? "eu" : "us";
  const statusPageUrl = STATUS_PAGE_URLS[resolvedRegion];

  try {
    const response = await fetcher(STATUS_API_URL, {
      signal: AbortSignal.timeout(5_000),
    });
    if (!response.ok) {
      return { status: "unknown", statusPageUrl };
    }

    return {
      status: getStatusForRegion(await response.json(), resolvedRegion),
      statusPageUrl,
    };
  } catch {
    return { status: "unknown", statusPageUrl };
  }
}

function getStatusForRegion(
  response: unknown,
  region: "us" | "eu",
): PlatformStatus["status"] {
  if (!isStatusResponse(response)) {
    return "unknown";
  }

  const groupName = region === "us" ? "US Cloud" : "EU Cloud";
  const groups = response.component_groups.filter(isStatusGroup);
  const group = groups.find(
    (candidate) => normalizeGroupName(candidate.name) === groupName,
  );
  if (!group || !Array.isArray(group.components)) {
    return "unknown";
  }

  const statuses = group.components
    .filter(isStatusComponent)
    .filter((component) => DESKTOP_COMPONENT_NAMES.has(component.name))
    .map((component) => normalizeStatus(component.status))
    .filter((status): status is KnownStatus => status !== null);

  if (statuses.length === 0) {
    return "unknown";
  }

  return statuses.reduce((worst, status) =>
    STATUS_PRIORITY[status] > STATUS_PRIORITY[worst] ? status : worst,
  );
}

function isStatusResponse(value: unknown): value is StatusResponse {
  return (
    typeof value === "object" &&
    value !== null &&
    "component_groups" in value &&
    Array.isArray(value.component_groups)
  );
}

function isStatusGroup(value: unknown): value is StatusGroup {
  return typeof value === "object" && value !== null;
}

function isStatusComponent(
  value: unknown,
): value is StatusComponent & { name: string } {
  return (
    typeof value === "object" &&
    value !== null &&
    "name" in value &&
    typeof value.name === "string"
  );
}

function normalizeGroupName(value: unknown): string {
  return typeof value === "string"
    ? value.replace(/[^\p{L}\p{N}\s]/gu, "").trim()
    : "";
}

function normalizeStatus(value: unknown): KnownStatus | null {
  if (value === "full_outage") {
    return "major_outage";
  }
  return typeof value === "string" && value in STATUS_PRIORITY
    ? (value as KnownStatus)
    : null;
}
