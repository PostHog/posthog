import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { humanizeHogFunctionType } from '../hog-function-utils'
import { HogFunctionConfigurationLogicProps } from './hogFunctionConfigurationLogic'
import { hogFunctionDraftLogic } from './hogFunctionDraftLogic'

export function HogFunctionDraftBanner({
    logicProps,
}: {
    logicProps: HogFunctionConfigurationLogicProps
}): JSX.Element | null {
    const logic = hogFunctionDraftLogic(logicProps)
    const { hogFunction, type, hasStagedDraft, draftActionPending, draftActionDisabledReason } = useValues(logic)
    const { publishDraft, discardDraft } = useActions(logic)

    if (!hogFunction || !hasStagedDraft) {
        return null
    }

    return (
        <LemonBanner type="warning">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="min-w-0 flex-1">
                    This {humanizeHogFunctionType(type)} has an unpublished draft. Publish to review the changes and
                    send them live.
                </span>
                <div className="flex gap-2 shrink-0">
                    <LemonButton
                        type="secondary"
                        status="danger"
                        size="small"
                        onClick={discardDraft}
                        loading={draftActionPending === 'discard'}
                        disabledReason={draftActionPending === 'discard' ? undefined : draftActionDisabledReason}
                        data-attr="hog-function-draft-discard"
                    >
                        Discard
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        size="small"
                        onClick={publishDraft}
                        loading={draftActionPending === 'publish'}
                        disabledReason={draftActionPending === 'publish' ? undefined : draftActionDisabledReason}
                        data-attr="hog-function-draft-publish"
                    >
                        Publish
                    </LemonButton>
                </div>
            </div>
        </LemonBanner>
    )
}
