import { AutocompleteItem, Button, cn } from "@posthog/quill";
import type { ComponentProps, ReactElement } from "react";

type ActivityRowSurfaceProps = ComponentProps<typeof Button> & {
  asOption?: boolean;
  optionValue?: string;
};

export function ActivityRowSurface({
  asOption = false,
  optionValue,
  className,
  children,
  ...props
}: ActivityRowSurfaceProps): ReactElement {
  const surfaceClassName = cn(
    "h-auto w-full items-start text-left",
    asOption &&
      "ring-offset-0 data-highlighted:border-transparent data-highlighted:bg-fill-hover data-highlighted:ring-0 [&>span]:w-full [&>span]:items-start [&>span]:gap-2",
    className,
  );

  if (asOption) {
    if (!optionValue) {
      throw new Error("Activity autocomplete options require a value");
    }
    return (
      <AutocompleteItem
        value={optionValue}
        nativeButton
        className={surfaceClassName}
        {...(props as ComponentProps<typeof AutocompleteItem>)}
      >
        {children}
      </AutocompleteItem>
    );
  }

  return (
    <Button left className={surfaceClassName} {...props}>
      {children}
    </Button>
  );
}
