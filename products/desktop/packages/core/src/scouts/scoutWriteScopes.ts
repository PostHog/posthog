/** One row in the write access picker. `scope` is the string the API stores and the token carries. */
export interface ScoutWriteScopeRow {
  scope: string;
  /** Heading the row sits under. Purely a label: the API stores a flat list of scopes. */
  group: "Analytics" | "Monitoring" | "Agents and skills" | "Data";
  label: string;
  description: string;
}

/**
 * The scopes a person may grant one agent, mirroring `SCOUT_GRANTABLE_WRITE_SCOPES` in
 * `posthog/temporal/oauth.py`. A scope the backend drops from the allowlist can still sit on an
 * old config: the picker shows nothing for it and drops it from the next save, because the API
 * would reject it. A scope added there needs a row here to be offered.
 *
 * Descriptions say what the scope reaches, because each one covers update and delete of every
 * object of its kind in the project, not only the ones the agent made.
 */
export const SCOUT_WRITE_SCOPE_ROWS: ScoutWriteScopeRow[] = [
  {
    scope: "dashboard:write",
    group: "Analytics",
    label: "Dashboards",
    description: "Create, update, and delete dashboards and their tiles",
  },
  {
    scope: "insight:write",
    group: "Analytics",
    label: "Insights",
    description: "Create, update, and delete saved insights",
  },
  {
    scope: "annotation:write",
    group: "Analytics",
    label: "Annotations",
    description:
      "Add, edit, and remove annotations, including organization-wide ones shared with other projects",
  },
  {
    scope: "alert:write",
    group: "Monitoring",
    label: "Alerts",
    description: "Create, update, and delete insight alerts",
  },
  {
    scope: "llm_skill:write",
    group: "Agents and skills",
    label: "Skills",
    description:
      "Create, update, and archive shared skills and their files, including the skills your other agents run from",
  },
  {
    scope: "warehouse_view:write",
    group: "Data",
    label: "Warehouse views",
    description:
      "Create, update, run, materialize, and delete views, and manage data quality checks on them",
  },
  {
    scope: "warehouse_table:write",
    group: "Data",
    label: "Warehouse tables",
    description:
      "Create tables, refresh their schema, and manage data quality checks on them",
  },
];

/** What every agent can write, whatever its grant. Shown so the picker is the whole picture. */
export const SCOUT_ALWAYS_GRANTED_ROWS: {
  label: string;
  description: string;
}[] = [
  { label: "Notebooks", description: "Every agent can write notebooks" },
  {
    label: "Self-driving and memory",
    description: "Its reports, findings, and shared agent memory",
  },
];

/** Short labels for the scopes an agent holds, for a header or a row summary. */
export function scoutWriteScopeLabels(
  scopes: readonly string[] | undefined,
): string[] {
  return SCOUT_WRITE_SCOPE_ROWS.filter((row) =>
    scopes?.includes(row.scope),
  ).map((row) => row.label);
}

/** The scopes the picker offers a row for, in row order. Anything else stored on a config is stale. */
export function offeredScoutWriteScopes(scopes: readonly string[]): string[] {
  return SCOUT_WRITE_SCOPE_ROWS.filter((row) => scopes.includes(row.scope)).map(
    (row) => row.scope,
  );
}

/** True when the two grants hold the same scopes, whatever order they are stored in. */
export function sameScoutWriteScopes(
  a: readonly string[],
  b: readonly string[],
): boolean {
  return [...a].sort().join() === [...b].sort().join();
}
