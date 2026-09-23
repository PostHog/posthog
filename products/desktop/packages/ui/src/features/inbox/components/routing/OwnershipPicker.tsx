import {
  Button,
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
  ComboboxTrigger,
} from "@posthog/quill";
import { useRef } from "react";

export function OwnershipPicker({
  label,
  value,
  options,
  onChange,
  disabled,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  const anchor = useRef<HTMLButtonElement>(null);
  return (
    <Combobox
      items={options}
      value={options.find((item) => item.value === value) ?? null}
      itemToStringLabel={(item) => item.label}
      itemToStringValue={(item) => item.value}
      onValueChange={(item) => {
        if (item) onChange(item.value);
      }}
    >
      <ComboboxTrigger
        render={
          <Button
            ref={anchor}
            variant="outline"
            disabled={disabled}
            aria-label={label}
            className="max-w-full truncate"
          />
        }
      >
        {options.find((item) => item.value === value)?.label ?? label}
      </ComboboxTrigger>
      <ComboboxContent anchor={anchor}>
        <ComboboxInput placeholder={`Search ${label.toLowerCase()}…`} />
        <ComboboxEmpty>No matches.</ComboboxEmpty>
        <ComboboxList>
          {(item: { value: string; label: string }) => (
            <ComboboxItem key={item.value} value={item}>
              {item.label}
            </ComboboxItem>
          )}
        </ComboboxList>
      </ComboboxContent>
    </Combobox>
  );
}
