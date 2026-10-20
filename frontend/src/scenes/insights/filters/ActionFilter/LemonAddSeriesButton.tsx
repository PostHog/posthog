import { IconPlusSmall } from '@posthog/icons'

import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'

export interface LemonAddSeriesButtonProps {
    label: string
    onClick: () => void
    disabled: boolean
    buttonType: LemonButtonProps['type']
    buttonProps: LemonButtonProps
}

export function LemonAddSeriesButton({
    label,
    onClick,
    disabled,
    buttonType,
    buttonProps,
}: LemonAddSeriesButtonProps): JSX.Element {
    return (
        <LemonButton
            type={buttonType}
            onClick={() => onClick()}
            data-attr="add-action-event-button"
            icon={<IconPlusSmall />}
            size="small"
            disabled={disabled}
            {...buttonProps}
        >
            {label}
        </LemonButton>
    )
}
