import { useActions, useValues } from 'kea'

import { IconTrash } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'

import { HogFunctionConfigurationLogicProps } from './hogFunctionConfigurationLogic'
import { hogFunctionDraftLogic } from './hogFunctionDraftLogic'

export function HogFunctionPublishDraftButton({
    logicProps,
}: {
    logicProps: HogFunctionConfigurationLogicProps
}): JSX.Element | null {
    const logic = hogFunctionDraftLogic(logicProps)
    const { hogFunction, hasStagedDraft, draftActionPending, draftActionDisabledReason } = useValues(logic)
    const { publishDraft, discardDraft } = useActions(logic)

    if (!hogFunction || !hasStagedDraft) {
        return null
    }

    return (
        <LemonButton
            type="primary"
            size="small"
            onClick={publishDraft}
            loading={draftActionPending === 'publish'}
            disabledReason={draftActionPending === 'publish' ? undefined : draftActionDisabledReason}
            tooltip="This has an unpublished draft. Publish to review the changes and send them live."
            data-attr="hog-function-draft-publish"
            // Discarding is rare and destructive, so it sits in the menu, as it does for workflows.
            sideAction={{
                'data-attr': 'hog-function-draft-actions',
                'aria-label': 'More draft actions',
                dropdown: {
                    placement: 'bottom-end',
                    overlay: (
                        <LemonMenuOverlay
                            items={[
                                {
                                    label: 'Discard draft',
                                    icon: <IconTrash />,
                                    status: 'danger',
                                    onClick: () => discardDraft(),
                                    disabledReason: draftActionDisabledReason,
                                    'data-attr': 'hog-function-draft-discard',
                                },
                            ]}
                        />
                    ),
                },
            }}
        >
            Publish
        </LemonButton>
    )
}
