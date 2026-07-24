import type {
  McpCategory,
  McpRecommendedServer,
  McpServerInstallation,
} from "@posthog/api-client/types";

export function filterServersByCategory(
  servers: McpRecommendedServer[],
  category: McpCategory | "all",
): McpRecommendedServer[] {
  if (category === "all") return servers;
  return servers.filter((s) => s.category === category);
}

export function filterServersByQuery(
  servers: McpRecommendedServer[],
  query: string,
): McpRecommendedServer[] {
  const q = query.trim().toLowerCase();
  if (!q) return servers;
  return servers.filter(
    (s) =>
      s.name.toLowerCase().includes(q) ||
      s.description?.toLowerCase().includes(q),
  );
}

export function filterInstallationsByQuery(
  installations: McpServerInstallation[],
  templatesById: Map<string, McpRecommendedServer>,
  query: string,
): McpServerInstallation[] {
  const q = query.trim().toLowerCase();
  if (!q) return installations;
  return installations.filter((i) => {
    const template = i.template_id ? templatesById.get(i.template_id) : null;
    const fields = [
      i.display_name,
      i.name,
      i.url,
      i.description,
      template?.name,
      template?.description,
    ];
    return fields.some((f) => f?.toLowerCase().includes(q));
  });
}
