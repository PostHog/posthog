import { Tooltip } from 'lib/lemon-ui/Tooltip'

const EXPLANATIONS = {
    model: 'No usage measurement is available for this model and date range.',
    job: 'Usage is measured once a day. Recent jobs update after the next daily measurement. Older measurements may be unavailable.',
}

export function UsageNotAvailable({ context }: { context: keyof typeof EXPLANATIONS }): JSX.Element {
    const explanation = EXPLANATIONS[context]

    return (
        <Tooltip title={explanation}>
            <span
                className="cursor-help border-b border-dotted text-secondary"
                tabIndex={0}
                aria-label={`N/A. ${explanation}`}
            >
                N/A
            </span>
        </Tooltip>
    )
}
