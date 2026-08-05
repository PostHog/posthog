import {
  type FlaggedMcpServerPayload,
  parseFlaggedMcpServerPayload,
} from "@posthog/core/local-mcp/schemas";
import { HOSTHOG_MCP_FLAG } from "@posthog/shared";
import { useFeatureFlagPayload } from "@posthog/ui/features/feature-flags/useFeatureFlagPayload";
import { useMemo } from "react";

/**
 * The internal marketplace server delivered by HOSTHOG_MCP_FLAG's payload.
 * Null when the flag is off for the user or the payload doesn't match the
 * schema.
 */
export function useFlaggedMcpServer(): FlaggedMcpServerPayload | null {
  const payload = useFeatureFlagPayload(HOSTHOG_MCP_FLAG);
  return useMemo(() => parseFlaggedMcpServerPayload(payload), [payload]);
}
