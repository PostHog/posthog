import { LemonTag, LemonTagProps } from 'lib/lemon-ui/LemonTag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

export type LabsStage = 'alpha' | 'beta'

export interface LabsTagProps {
    stage: LabsStage
    size?: LemonTagProps['size']
    className?: string
}

const LABS_DESCRIPTION = 'PostHog labs allows releases early to learn from real users, not imagineer perfection.'

export function LabsTag({ stage, size, className }: LabsTagProps): JSX.Element {
    return (
        <Tooltip
            title={
                <span>
                    {LABS_DESCRIPTION} <strong>{stage.toUpperCase()}</strong>
                </span>
            }
        >
            <LemonTag type="completion" size={size} className={className}>
                LABS
            </LemonTag>
        </Tooltip>
    )
}
