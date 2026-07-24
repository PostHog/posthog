import { CaretDown, HardDrives, Plus } from "@phosphor-icons/react";
import {
  Button,
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
  ComboboxListFooter,
  ComboboxTrigger,
} from "@posthog/quill";
import { useEffect, useRef, useState } from "react";
import { useEnvironments } from "./useEnvironments";

interface EnvironmentSelectorProps {
  repoPath: string | null;
  value: string | null;
  onChange: (environmentId: string | null) => void;
  disabled?: boolean;
  onCreateEnvironment?: () => void;
}

const NONE_VALUE = "__none__";

export function EnvironmentSelector({
  repoPath,
  value,
  onChange,
  disabled = false,
  onCreateEnvironment,
}: EnvironmentSelectorProps) {
  const [open, setOpen] = useState(false);
  const anchorRef = useRef<HTMLDivElement>(null);

  const { data: environments = [] } = useEnvironments(repoPath);

  useEffect(() => {
    if (value === null && environments.length > 0) {
      onChange(environments[0].id);
    }
  }, [value, environments, onChange]);

  const selectedEnvironment = environments.find((env) => env.id === value);
  const displayText = selectedEnvironment?.name ?? "No environment";

  if (environments.length === 0) {
    return null;
  }

  const handleChange = (newValue: string | null) => {
    onChange(newValue === NONE_VALUE ? null : newValue || null);
    setOpen(false);
  };

  const handleOpenSettings = () => {
    setOpen(false);
    onCreateEnvironment?.();
  };

  const isDisabled = disabled || !repoPath;

  const CREATE_ENV_ACTION = "__create_env__";
  const allItems = [
    NONE_VALUE,
    ...environments.map((env) => env.id),
    ...(onCreateEnvironment ? [CREATE_ENV_ACTION] : []),
  ];

  return (
    <Combobox
      items={allItems}
      value={value ?? NONE_VALUE}
      onValueChange={(v) => handleChange(v as string | null)}
      open={open}
      onOpenChange={setOpen}
      disabled={isDisabled}
    >
      <div ref={anchorRef} className="inline-flex">
        <ComboboxTrigger
          render={
            <Button
              variant="outline"
              size="sm"
              disabled={isDisabled}
              aria-label="Environment"
              title={displayText}
            >
              <HardDrives size={14} weight="regular" className="shrink-0" />
              <span className="min-w-0 truncate">{displayText}</span>
              <CaretDown
                size={10}
                weight="bold"
                className="text-muted-foreground"
              />
            </Button>
          }
        />
      </div>
      <ComboboxContent
        anchor={anchorRef}
        side="bottom"
        sideOffset={6}
        className="min-w-[220px]"
      >
        <ComboboxInput
          placeholder="Search environments..."
          showTrigger={false}
        />
        <ComboboxEmpty>No environments found.</ComboboxEmpty>

        <ComboboxList className="max-h-[min(14rem,calc(var(--available-height,14rem)-5rem))]">
          {(itemValue: string) => {
            if (itemValue === CREATE_ENV_ACTION) {
              return (
                <ComboboxListFooter key="footer">
                  <ComboboxItem
                    value={CREATE_ENV_ACTION}
                    onClick={handleOpenSettings}
                  >
                    <Plus size={11} weight="bold" />
                    Create local environment
                  </ComboboxItem>
                </ComboboxListFooter>
              );
            }
            if (itemValue === NONE_VALUE) {
              return (
                <ComboboxItem
                  key={NONE_VALUE}
                  value={NONE_VALUE}
                  title="No environment"
                  className="relative"
                >
                  No environment
                </ComboboxItem>
              );
            }
            const env = environments.find((e) => e.id === itemValue);
            if (!env) return null;
            return (
              <ComboboxItem
                key={env.id}
                value={env.id}
                title={env.name}
                className="relative"
              >
                {env.name}
              </ComboboxItem>
            );
          }}
        </ComboboxList>
      </ComboboxContent>
    </Combobox>
  );
}
