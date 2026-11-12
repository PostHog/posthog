import { useValues } from 'kea'

import { IconWarning } from '@posthog/icons'
import { Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { pluralize } from 'lib/utils/strings'

import { dataQualityChecksLogic } from 'products/data_quality/frontend/dataQualityChecksLogic'

import type { NodeDetailTestsSubjectType } from './NodeDetailTests'

const TONES: Record<string, string> = {
    failing: 'text-destructive-foreground',
    warn: 'text-warning-foreground',
    erroring: 'text-warning-foreground',
}

export function QuillNodeDetailTestsTabLabel({
    subjectType,
    subjectId,
}: {
    subjectType: NodeDetailTestsSubjectType
    subjectId: string
}): JSX.Element {
    const { health } = useValues(dataQualityChecksLogic({ subjectType, subjectId }))
    const tone = health ? TONES[health.health] : undefined
    const explanation =
        health?.health === 'erroring'
            ? 'A check could not run'
            : `${pluralize(health?.checks_failing ?? 0, 'check')} failing`

    return (
        <span className="flex items-center gap-1">
            Data quality
            {tone && (
                <Tooltip>
                    <TooltipTrigger render={<span aria-label={explanation} className={`flex ${tone}`} />}>
                        <IconWarning />
                    </TooltipTrigger>
                    <TooltipContent>{explanation}</TooltipContent>
                </Tooltip>
            )}
        </span>
    )
}
