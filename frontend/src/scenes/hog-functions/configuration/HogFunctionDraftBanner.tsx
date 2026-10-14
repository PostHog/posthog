import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

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
            <div className="flex flex-col gap-2 min-w-0">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-col gap-1 min-w-0 flex-1">
                        <span className="font-semibold">Unpublished changes</span>
                        <span>
                            Changes to this {humanizeHogFunctionType(type)} were staged{' '}
                            {hogFunction.draft_updated_at ? <TZLabel time={hogFunction.draft_updated_at} /> : null} and
                            are not live yet. The live version keeps running until you publish them. Publish shows you
                            the changes before they go live. If you save edits below, they change the live version, and
                            publishing replaces them with the staged changes.
                        </span>
                    </div>
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
            </div>
        </LemonBanner>
    )
}
