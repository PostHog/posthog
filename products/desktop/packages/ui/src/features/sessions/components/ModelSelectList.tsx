import type {
  SessionConfigSelectOption,
  SessionConfigSelectOptions,
} from "@agentclientprotocol/sdk";
import { compareModelsForPicker } from "@posthog/agent/gateway-models";
import {
  DropdownMenuGroup,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuSeparator,
} from "@posthog/quill";
import { isSelectGroup } from "@posthog/shared";
import { gateRestrictedModelPick } from "@posthog/ui/features/billing/modelGate";
import { ModelCostFooter } from "@posthog/ui/features/sessions/components/ModelCostChip";
import { ModelRadioItem } from "@posthog/ui/features/sessions/components/ModelRadioItem";
import { Fragment } from "react";
import { flattenSelectOptions } from "../sessionStore";

interface ModelSelectListProps {
  options: SessionConfigSelectOptions;
  currentValue?: string;
  onSelect: (value: string) => void;
  /** A plan-restricted pick opened the upgrade gate instead; close the menu. */
  onGated?: () => void;
  /** Names why the current billing source cannot run a model, if it cannot. */
  unavailableReason?: (modelId: string) => string | undefined;
}

const renderEntries = (
  list: SessionConfigSelectOption[],
  unavailableReason?: (modelId: string) => string | undefined,
) =>
  list
    .toSorted((a, b) => compareModelsForPicker(a.value, b.value))
    .map((model) => (
      <ModelRadioItem
        key={model.value}
        model={model}
        closeOnClick={false}
        unavailableReason={unavailableReason?.(model.value)}
      />
    ));

/**
 * The model radio list every picker shares: one identical catalog, grouped by
 * provider, so the menu looks the same whichever harness is active. The
 * harness consequence of a pick is the caller's decision.
 */
export function ModelSelectList({
  options,
  currentValue,
  onSelect,
  onGated,
  unavailableReason,
}: ModelSelectListProps) {
  const entries = flattenSelectOptions(options);
  const groups = isSelectGroup(options) ? options : [];

  return (
    <>
      <DropdownMenuRadioGroup
        value={currentValue ?? ""}
        onValueChange={(value) => {
          if (unavailableReason?.(value)) return;
          // A plan-restricted model opens the upgrade gate instead of
          // becoming the selection.
          if (gateRestrictedModelPick(entries, value)) {
            onGated?.();
            return;
          }
          onSelect(value);
        }}
      >
        {groups.length > 0
          ? groups.map((group, index) => (
              <Fragment key={group.group}>
                {index > 0 && <DropdownMenuSeparator />}
                <DropdownMenuGroup>
                  {groups.length > 1 && group.name && (
                    <DropdownMenuLabel>{group.name}</DropdownMenuLabel>
                  )}
                  {renderEntries(group.options, unavailableReason)}
                </DropdownMenuGroup>
              </Fragment>
            ))
          : renderEntries(entries, unavailableReason)}
      </DropdownMenuRadioGroup>
      <ModelCostFooter />
    </>
  );
}
