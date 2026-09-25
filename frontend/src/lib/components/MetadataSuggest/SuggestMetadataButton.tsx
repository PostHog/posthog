import { IconSparkles } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

export const METADATA_SUGGESTION_DATA_NOTICE =
    "A PostHog-hosted AI model picks from options built from this insight. It reads the name, the description, your project's tags and a plain outline of the query. Filter values that look like personal data are left out."

export interface SuggestMetadataButtonProps {
    /** What the button fills in, shown as the tooltip title. Example: "Suggest a title". */
    label: string
    onClick: () => void
    loading?: boolean
    disabledReason?: string
    /** Frozen once shipped: autocapture dashboards and Playwright find the button by it. */
    dataAttr: string
    size?: 'xsmall' | 'small'
}

/** A sparkle icon button that asks the Jev decision model to pick a value for a metadata field. */
export function SuggestMetadataButton({
    label,
    onClick,
    loading = false,
    disabledReason,
    dataAttr,
    size = 'small',
}: SuggestMetadataButtonProps): JSX.Element {
    return (
        <Tooltip
            title={
                <div className="flex flex-col gap-1">
                    <span className="font-semibold">{loading ? 'Picking...' : label}</span>
                    <span>{METADATA_SUGGESTION_DATA_NOTICE}</span>
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
