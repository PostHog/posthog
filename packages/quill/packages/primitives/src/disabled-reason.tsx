import * as React from 'react'

import { Label } from './label'
import { cn } from './lib/utils'
import { hasTooltipContent, withDisabledReason } from './with-tooltip'

/** A control inside a FieldLabel with a reason ignores its own reason, so two tooltip triggers never nest. */
const FieldDisabledReasonContext = React.createContext<string | null>(null)

export const FieldDisabledReasonProvider = FieldDisabledReasonContext.Provider

/** Screen readers and touch never see a tooltip, so the reason is also hidden text for `aria-describedby`. */
function DisabledReasonDescription({ id, reason }: { id: string; reason: React.ReactNode }): React.ReactElement | null {
    return hasTooltipContent(reason) ? (
        <span id={id} hidden>
            {reason}
        </span>
    ) : null
}

/** A disabled control ignores the pointer, but its label does not, so the label is the tooltip trigger. */
export const ReasonLabel = React.forwardRef<
    React.ComponentRef<typeof Label>,
    React.ComponentProps<typeof Label> & { disabledReason: React.ReactNode; reasonId: string; disabled?: boolean }
>(function ReasonLabel({ className, disabledReason, reasonId, disabled, ...props }, ref) {
    const hasReason = hasTooltipContent(disabledReason)
    return (
        <>
            {withDisabledReason(
                <Label
                    ref={ref}
                    data-slot="field-label"
                    data-disabled={disabled || hasReason ? '' : undefined}
                    aria-describedby={hasReason ? reasonId : undefined}
                    className={cn('quill-field__label group/field-label peer/field-label flex w-fit gap-2', className)}
                    {...props}
                />,
                disabledReason,
                { target: 'self', focusable: true }
            )}
            <DisabledReasonDescription id={reasonId} reason={disabledReason} />
        </>
    )
})

/** Spread `rootProps` after the caller's props, so its merged `aria-describedby` wins. */
export function useDisabledControl({
    disabled,
    disabledReason,
    label,
    ariaDescribedBy,
}: {
    disabled: boolean | undefined
    disabledReason: React.ReactNode
    label: React.ReactNode
    ariaDescribedBy: string | undefined
}): {
    rootProps: { disabled: boolean; 'aria-describedby': string | undefined }
    wrap: (control: React.ReactElement) => React.ReactElement
} {
    const reasonId = React.useId()
    const fieldReasonId = React.useContext(FieldDisabledReasonContext)
    const reason = fieldReasonId === null ? disabledReason : undefined
    const hasReason = hasTooltipContent(reason)
    const isDisabled = !!disabled || hasReason || fieldReasonId !== null
    const describedBy =
        [ariaDescribedBy, fieldReasonId ?? (hasReason ? reasonId : undefined)].filter(Boolean).join(' ') || undefined
    const hasLabel = label !== undefined && label !== null && label !== false && label !== ''
    return {
        rootProps: { disabled: isDisabled, 'aria-describedby': describedBy },
        wrap: (control) =>
            hasLabel ? (
                <ReasonLabel
                    data-slot="control-label"
                    disabled={isDisabled}
                    disabledReason={reason}
                    reasonId={reasonId}
                >
                    {control}
                    <span data-slot="control-label-text">{label}</span>
                </ReasonLabel>
            ) : (
                <>
                    {withDisabledReason(control, reason, { target: 'inline', focusable: true })}
                    <DisabledReasonDescription id={reasonId} reason={reason} />
                </>
            ),
    }
}
