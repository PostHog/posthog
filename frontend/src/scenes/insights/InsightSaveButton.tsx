import { LemonButton, LemonButtonWithSideAction } from 'lib/components/LemonButton'
import React from 'react'

export function InsightSaveButton({
    saveAs,
    saveInsight,
    isSaved,
    filtersChanged,
    addingToDashboard,
}: {
    saveAs: () => void
    saveInsight: (options: Record<string, any>) => void
    isSaved: boolean | undefined
    filtersChanged: boolean
    addingToDashboard: boolean
}): JSX.Element {
    const disabled = isSaved && !filtersChanged
    const saveAsAvailable = isSaved && !addingToDashboard

    return (
        <LemonButtonWithSideAction
            style={{ marginLeft: 8 }}
            type="primary"
            onClick={() => saveInsight({ setViewMode: true })}
            data-attr="insight-save-button"
            disabled={disabled}
            sideAction={{
                popup: {
                    overlay: (
                        <>
                            <LemonButton
                                onClick={saveInsight}
                                data-attr="insight-save-and-continue"
                                type="stealth"
                                fullWidth
                            >
                                {addingToDashboard ? 'Save, add to dashboard' : 'Save'} & continue editing
                            </LemonButton>
                            {saveAsAvailable && (
                                <LemonButton
                                    onClick={saveAs}
                                    data-attr="insight-save-as-new-insight"
                                    type="stealth"
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
