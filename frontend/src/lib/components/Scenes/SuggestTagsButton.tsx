import { IconSparkles } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

export interface SuggestTagsButtonProps {
    onClick: () => void
    loading: boolean
    /** Saving tags at the same time would race the suggestion, and one save would overwrite the other. */
    saving?: boolean
    /** Frozen once shipped: autocapture dashboards and Playwright find the button by `${dataAttrKey}-tags-suggest`. */
    dataAttrKey: string
}

/** A sparkle icon button that asks the Jev decision model which of the project's existing tags apply. */
export function SuggestTagsButton({ onClick, loading, saving, dataAttrKey }: SuggestTagsButtonProps): JSX.Element {
    return (
        <Tooltip
            title={
                <div className="flex flex-col gap-1">
                    <span className="font-semibold">{loading ? 'Picking...' : 'Suggest tags'}</span>
                    <span>
                        A PostHog-hosted AI model checks which of your project's existing tags fit this insight. It
                        reads the name, the description, the tag names and a plain outline of the query, without filter
                        values.
                    </span>
                </div>
            }
        >
            <LemonButton
                icon={<IconSparkles />}
                size="xsmall"
                type="tertiary"
                onClick={onClick}
                loading={loading}
                disabledReason={saving ? 'Saving tags...' : undefined}
                aria-label="Suggest tags"
                data-attr={`${dataAttrKey}-tags-suggest`}
                className="shrink-0 border border-dashed border-accent"
            />
        </Tooltip>
    )
}
