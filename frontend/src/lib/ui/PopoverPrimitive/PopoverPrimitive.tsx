import * as React from "react"
import * as PopoverPrimitiveBase from "@radix-ui/react-popover"

import { cn } from "lib/utils/css-classes"

function PopoverPrimitive({
  ...props
}: React.ComponentProps<typeof PopoverPrimitiveBase.Root>) {
  return <PopoverPrimitiveBase.Root data-slot="popover" {...props} />
}

function PopoverPrimitiveTrigger({
  ...props
}: React.ComponentProps<typeof PopoverPrimitiveBase.Trigger>) {
  return <PopoverPrimitiveBase.Trigger data-slot="popover-trigger" {...props} />
}

function PopoverPrimitiveContent({
  className,
  align = "center",
  sideOffset = 4,
  ...props
}: React.ComponentProps<typeof PopoverPrimitiveBase.Content>) {
  return (
    // <PopoverPrimitiveBase.Portal>
      <PopoverPrimitiveBase.Content
        data-slot="popover-content"
        align={align}
        sideOffset={sideOffset}
        className={cn(
          "data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 outline-hidden",
          className
        )}
        {...props}
      />
    // </PopoverPrimitiveBase.Portal>
  )
}

function PopoverPrimitiveAnchor({
  ...props
}: React.ComponentProps<typeof PopoverPrimitiveBase.Anchor>) {
  return <PopoverPrimitiveBase.Anchor data-slot="popover-anchor" {...props} />
}

export { PopoverPrimitive, PopoverPrimitiveTrigger, PopoverPrimitiveContent, PopoverPrimitiveAnchor }
