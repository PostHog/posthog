import { IconSparkles } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

export const TYPESAFE_DATA_NOTICE =
    'This sends the name, description, query and tags to TypeSafe. TypeSafe is not on the PostHog list of subprocessors, so your agreements with PostHog do not cover it.'

export interface TypesafeSuggestButtonProps {
    /** What the button fills in, shown as the tooltip title. Example: "Suggest a title". */
    label: string
    onClick: () => void
    loading?: boolean
    disabledReason?: string
    /** Frozen once shipped: autocapture dashboards and Playwright find the button by it. */
    dataAttr: string
    size?: 'xsmall' | 'small'
}

/** A sparkle icon button that asks TypeSafe's Jev model to pick a value for a metadata field. */
export function TypesafeSuggestButton({
    label,
    onClick,
    loading = false,
    disabledReason,
    dataAttr,
    size = 'small',
}: TypesafeSuggestButtonProps): JSX.Element {
    return (
        <Tooltip
            title={
                <div className="flex flex-col gap-1">
                    <span className="font-semibold">{loading ? 'Asking TypeSafe...' : label}</span>
                    <span>{TYPESAFE_DATA_NOTICE}</span>
                </div>
            }
        >
            <LemonButton
                icon={<IconSparkles />}
                size={size}
                type="tertiary"
                onClick={onClick}
                loading={loading}
                disabledReason={disabledReason}
                aria-label={label}
                data-attr={dataAttr}
                className="shrink-0 border border-dashed border-accent"
            />
        </Tooltip>
    )
}
