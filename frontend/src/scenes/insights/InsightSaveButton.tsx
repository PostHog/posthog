import { LemonButton } from 'lib/lemon-ui/LemonButton'

export function InsightSaveButton({
    saveAs,
    saveInsight,
    isSaved,
    insightSaving,
    insightChanged,
    addingToDashboard,
    onSaveAndAddToDashboard,
}: {
    saveAs: () => void
    saveInsight: (redirectToViewMode?: boolean) => void
    isSaved: boolean | undefined
    insightSaving: boolean
    insightChanged: boolean
    addingToDashboard: boolean
    // When provided (B branch of the add-to-dashboard A/A/B test), adds a "Save & add to dashboard" dropdown option.
    onSaveAndAddToDashboard?: () => void
}): JSX.Element {
    const disabled = isSaved && !insightChanged
    const saveAsAvailable = isSaved && !addingToDashboard

    return (
        <LemonButton
            type="primary"
            onClick={() => saveInsight(true)}
            data-attr="insight-save-button"
            disabled={disabled}
            size="small"
            loading={!disabled && insightSaving}
            sideAction={{
                dropdown: {
                    placement: 'bottom-end',
                    overlay: (
                        <>
                            {!disabled && (
                                <LemonButton
                                    onClick={() => saveInsight(false)}
                                    data-attr="insight-save-and-continue"
                                    fullWidth
                                >
                                    {addingToDashboard ? 'Save, add to dashboard' : 'Save'} & continue editing
                                </LemonButton>
                            )}
                            {!disabled && onSaveAndAddToDashboard && (
                                <LemonButton
                                    onClick={() => onSaveAndAddToDashboard()}
                                    data-attr="insight-save-and-add-to-dashboard"
                                    fullWidth
                                >
                                    Save & add to dashboard
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
