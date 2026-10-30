import { IconPlus } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

/** A dotted slot to add an evaluation, for teams that only run a few. */
export function EvaluationCreateSlot({ className }: { className?: string }): JSX.Element {
    return (
        <Link
            to={urls.aiObservabilityEvaluationTemplates()}
            subtle
            className={cn(
                'flex items-center justify-center gap-1.5 rounded px-3 py-2 text-sm font-medium text-secondary hover:text-primary border-2 border-dotted border-secondary hover:border-accent',
                className
            )}
            data-attr="evaluation-overview-create-slot"
        >
            <IconPlus />
            <span>Create evaluation</span>
        </Link>
    )
}
