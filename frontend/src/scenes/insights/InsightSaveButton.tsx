import { LemonButton, LemonButtonWithSideAction } from 'lib/components/LemonButton'
import React from 'react'

export function InsightSaveButton({
    saveAs,
    saveInsight,
    isSaved,
    insightSaving,
    insightChanged,
    addingToDashboard,
}: {
    saveAs: () => void
    saveInsight: (redirect: boolean) => void
    isSaved: boolean | undefined
    insightSaving: boolean
    insightChanged: boolean
    addingToDashboard: boolean
}): JSX.Element {
    const disabled = isSaved && !insightChanged
    const saveAsAvailable = isSaved && !addingToDashboard

    return (
        <LemonButtonWithSideAction
            type="primary"
            onClick={() => saveInsight(true)}
            data-attr="insight-save-button"
            disabled={disabled}
            loading={!disabled && insightSaving}
            data-tooltip="insight-save-button"
            sideAction={{
                popup: {
                    placement: 'bottom-end',
                    overlay: (
                        <>
                            {!disabled && (
                                <LemonButton
                                    onClick={() => saveInsight(false)}
                                    data-attr="insight-save-and-continue"
                                    status="stealth"
                                    fullWidth
                                >
                                    {addingToDashboard ? 'Save, add to dashboard' : 'Save'} & continue editing
                                </LemonButton>
                            )}
                            {saveAsAvailable && (
                                <LemonButton
                                    onClick={saveAs}
                                    data-attr="insight-save-as-new-insight"
                                    status="stealth"
                                    fullWidth
                                >
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
            {disabled ? 'No changes to be saved' : addingToDashboard ? 'Save & add to dashboard' : 'Save'}
        </LemonButtonWithSideAction>
    )
}
