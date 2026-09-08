export interface ScoutWriteScopeRow {
  scope: string;
  group: "Analytics" | "Monitoring" | "Agents and skills" | "Data";
  label: string;
  description: string;
}

/**
 * Mirrors `SCOUT_GRANTABLE_WRITE_SCOPES` in `posthog/temporal/oauth.py`: a scope added there needs
 * a row here to be offered, and its description has to say what it reaches project-wide.
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

export function scoutWriteScopeLabels(
  scopes: readonly string[] | undefined,
): string[] {
  return SCOUT_WRITE_SCOPE_ROWS.filter((row) =>
    scopes?.includes(row.scope),
  ).map((row) => row.label);
}

// A dropped scope can still sit on an old config, and resending one gets the update rejected.
export function offeredScoutWriteScopes(scopes: readonly string[]): string[] {
  return SCOUT_WRITE_SCOPE_ROWS.filter((row) => scopes.includes(row.scope)).map(
    (row) => row.scope,
  );
}

export function sameScoutWriteScopes(
  a: readonly string[],
  b: readonly string[],
): boolean {
  return [...a].sort().join() === [...b].sort().join();
}

function groupRows(): Map<ScoutWriteScopeRow["group"], ScoutWriteScopeRow[]> {
  const groups = new Map<ScoutWriteScopeRow["group"], ScoutWriteScopeRow[]>();
  for (const row of SCOUT_WRITE_SCOPE_ROWS) {
    const rows = groups.get(row.group);
    if (rows) {
      rows.push(row);
    } else {
      groups.set(row.group, [row]);
    }
  }
  return groups;
}

export const SCOUT_WRITE_SCOPE_GROUPS: ReadonlyMap<
  ScoutWriteScopeRow["group"],
  ScoutWriteScopeRow[]
> = groupRows();
