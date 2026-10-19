import { useValues } from 'kea'

import { LemonTag } from '@posthog/lemon-ui'

import { HogFunctionConfigurationLogicProps } from './hogFunctionConfigurationLogic'
import { hogFunctionDraftLogic } from './hogFunctionDraftLogic'

/** Mirrors the status tags in the workflows status bar, so both products describe a staged draft the same way. */
export function HogFunctionDraftStatusBar({
    logicProps,
}: {
    logicProps: HogFunctionConfigurationLogicProps
}): JSX.Element | null {
    const { hogFunction, hasStagedDraft } = useValues(hogFunctionDraftLogic(logicProps))

    // A disabled function without a draft has nothing live to protect; the Status card already says so.
    if (!hogFunction || (!hogFunction.enabled && !hasStagedDraft)) {
        return null
    }

    return (
        <div className="flex items-center gap-3 px-2 py-1.5 border rounded bg-surface-secondary min-w-0 flex-wrap">
            {hasStagedDraft ? (
                <LemonTag type="warning">Editing draft</LemonTag>
            ) : (
                <LemonTag type="success">Live</LemonTag>
            )}
            {hogFunction.enabled && (
                <span className="text-xs text-secondary truncate">
                    {hasStagedDraft
                        ? 'The live version keeps running until you publish.'
                        : 'Agent changes save as a draft.'}
                </span>
            )}
        </div>
    )
}
