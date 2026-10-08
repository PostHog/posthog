import type { Signal } from "@posthog/shared/domain-types";
import { getCloudUrlFromRegion } from "@/features/auth/lib/constants";
import type { CloudRegion } from "@/features/auth/types";

export interface ConversationsTicketExtra {
  ticket_number?: number;
  status?: string;
  priority?: string;
  email_subject?: string;
}

export function conversationsTicketRef(
  signal: Signal,
  extra: ConversationsTicketExtra,
): string | number | null {
  if (
    typeof extra.ticket_number === "number" &&
    Number.isInteger(extra.ticket_number) &&
    extra.ticket_number > 0
  ) {
    return extra.ticket_number;
  }
  return signal.source_id || null;
}

export function supportTicketUrl(
  ticketRef: string | number,
  options: {
    projectId: number | null;
    cloudRegion: CloudRegion | null;
  },
): string | null {
  const { projectId, cloudRegion } = options;
  if (projectId === null || cloudRegion === null) return null;
  return `${getCloudUrlFromRegion(cloudRegion)}/project/${projectId}/support/tickets/${encodeURIComponent(String(ticketRef))}`;
}
