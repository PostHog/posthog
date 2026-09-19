import { CheckIcon } from "@phosphor-icons/react";
import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import {
  offeredScoutWriteScopes,
  SCOUT_ALWAYS_GRANTED_ROWS,
  SCOUT_WRITE_SCOPE_GROUPS,
  sameScoutWriteScopes,
  scoutWriteScopeLabels,
} from "@posthog/core/scouts/scoutWriteScopes";
import { Badge, Button, Switch } from "@posthog/quill";
import { useState } from "react";
import type { ScoutConfigUpdate } from "../hooks/useScoutConfigMutations";

/**
 * What one agent may write in the project. The only control in this form that does not save on
 * change: widening what an unattended agent changes should take a deliberate save. The switches
 * stay live for everyone, because the client cannot tell who may save; the API refuses the rest.
 */
export function ScoutWriteAccessSection({
  config,
  onUpdate,
}: {
  config: ScoutConfig;
  onUpdate: (configId: string, updates: ScoutConfigUpdate) => void;
}) {
  const saved = config.write_scopes ?? [];
  // Null until something is toggled, so a rejected save leaves the rows where the server has them.
  const [draft, setDraft] = useState<string[] | null>(null);
  const selected = draft ?? saved;
  const granted = new Set(selected);
  const changed = !sameScoutWriteScopes(selected, saved);
  const heldLabels = scoutWriteScopeLabels(saved);

  const toggleScope = (scope: string, grant: boolean) => {
    const held = offeredScoutWriteScopes(selected);
    setDraft(
      grant ? [...held, scope] : held.filter((offered) => offered !== scope),
    );
  };

  return (
    <div className="flex flex-col gap-3 rounded-(--radius-md) border border-border bg-(--color-panel-solid) px-3.5 py-3">
      <div
        className="flex flex-wrap items-center gap-1.5"
        data-attr="scout-write-access-held"
      >
        {heldLabels.length > 0 ? (
          heldLabels.map((label) => (
            <Badge key={label} variant={config.emit ? "info" : "default"}>
              {label}
            </Badge>
          ))
        ) : (
          <span className="text-[11.5px] text-gray-10">Read only</span>
        )}
        {heldLabels.length > 0 && !config.emit ? (
          <span className="text-[11.5px] text-gray-10">
            Inactive during dry run
          </span>
        ) : null}
      </div>

      {[...SCOUT_WRITE_SCOPE_GROUPS].map(([group, rows]) => (
        <div key={group} className="flex flex-col gap-2">
          <span className="font-medium text-[11px] text-gray-10 uppercase tracking-wide">
            {group}
          </span>
          {rows.map((row) => (
            <div
              key={row.scope}
              className="flex items-start justify-between gap-3"
            >
              <span className="flex min-w-0 flex-col">
                <span className="text-[12.5px] text-gray-12">{row.label}</span>
                <span className="text-[11.5px] text-gray-10">
                  {row.description}
                </span>
              </span>
              <Switch
                size="sm"
                checked={granted.has(row.scope)}
                onCheckedChange={(checked) => toggleScope(row.scope, checked)}
                aria-label={`Let this agent write ${row.label.toLowerCase()}`}
              />
            </div>
          ))}
        </div>
      ))}

      <div className="flex flex-col gap-2">
        <span className="font-medium text-[11px] text-gray-10 uppercase tracking-wide">
          Always granted
        </span>
        {SCOUT_ALWAYS_GRANTED_ROWS.map((row) => (
          <div key={row.label} className="flex items-center gap-2">
            <CheckIcon size={13} className="shrink-0 text-(--green-11)" />
            <span className="shrink-0 text-[12.5px] text-gray-12">
              {row.label}
            </span>
            <span className="min-w-0 truncate text-[11.5px] text-gray-10">
              {row.description}
            </span>
          </div>
        ))}
      </div>

      {selected.length > 0 ? (
        <p className="text-(--amber-11) text-[11.5px]">
          Write access covers the whole project. An agent that can write
          dashboards can change or delete any dashboard here, not only the ones
          it created. Annotations also include organization-wide ones that other
          projects see, and skills include the ones your other agents run from.
          Most deletes here can be undone. Deleted alerts and deleted data
          quality checks cannot. Changes apply from the agent's next run.
        </p>
      ) : null}

      <div className="flex justify-end">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={!changed}
          onClick={() => {
            onUpdate(config.id, { write_scopes: selected });
            setDraft(null);
          }}
          data-attr="scout-write-access-save"
        >
          Save write access
        </Button>
      </div>
    </div>
  );
}
