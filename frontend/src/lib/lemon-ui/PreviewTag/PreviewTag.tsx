import { LemonTag, LemonTagProps } from 'lib/lemon-ui/LemonTag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

export type PreviewStage = 'alpha' | 'beta'

export interface PreviewTagProps {
    stage: PreviewStage
    size?: LemonTagProps['size']
    className?: string
}

const PREVIEW_DESCRIPTION =
    'PostHog ships features as previews so we can learn from real users, not imagineer perfection.'

export function PreviewTag({ stage, size, className }: PreviewTagProps): JSX.Element {
    return (
        <Tooltip
            title={
                <span>
                    {PREVIEW_DESCRIPTION} <strong>{stage.toUpperCase()}</strong>
                </span>
            }
        >
            <LemonTag
                type="completion"
                size={size}
                className={className}
                aria-label={`PostHog preview feature, currently in ${stage}`}
            >
                PREVIEW
            </LemonTag>
        </Tooltip>
    )
}
