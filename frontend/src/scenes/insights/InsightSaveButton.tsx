import { useActions } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { InsightEventSource } from 'lib/utils/eventUsageLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'

import { ItemMode } from '~/types'

export function InsightSaveButton({
    saveAs,
    saveInsight,
    isSaved,
    insightSaving,
    insightChanged,
    addingToDashboard,
}: {
    saveAs: () => void
    saveInsight: (redirectToViewMode?: () => void) => void
    isSaved: boolean | undefined
    insightSaving: boolean
    insightChanged: boolean
    addingToDashboard: boolean
}): JSX.Element {
    const disabled = isSaved && !insightChanged
    const saveAsAvailable = isSaved && !addingToDashboard
    const { setInsightMode } = useActions(insightSceneLogic)

    return (
        <LemonButton
            type="primary"
            onClick={() => saveInsight(() => setInsightMode(ItemMode.View, InsightEventSource.InsightHeader))}
            data-attr="insight-save-button"
            disabled={disabled}
            loading={!disabled && insightSaving}
            sideAction={{
                dropdown: {
                    placement: 'bottom-end',
                    overlay: (
                        <>
                            {!disabled && (
                                <LemonButton
                                    onClick={() => saveInsight()}
                                    data-attr="insight-save-and-continue"
                                    fullWidth
                                >
                                    {addingToDashboard ? 'Save, add to dashboard' : 'Save'} & continue editing
                                </LemonButton>
                            )}
                            {saveAsAvailable && (
                                <LemonButton onClick={() => saveAs()} data-attr="insight-save-as-new-insight" fullWidth>
                                    Save as…
                                </LemonButton>
                            )}
                        </>
                    ),
                },
                disabled: disabled && !saveAsAvailable,
                'data-attr': 'insight-save-dropdown',
            }}
        >
            {disabled ? 'No changes' : addingToDashboard ? 'Save & add to dashboard' : 'Save'}
        </LemonButton>
    )
}
