import { LemonButton } from 'lib/lemon-ui/LemonButton'

export function InsightSaveButton({
    saveAs,
    saveUnder,
    saveInsight,
    isSaved,
    insightSaving,
    insightChanged,
    addingToDashboard,
}: {
    saveAs: () => void
    saveUnder?: () => void
    saveInsight: (redirectToViewMode?: boolean) => void
    isSaved: boolean | undefined
    insightSaving: boolean
    insightChanged: boolean
    addingToDashboard: boolean
}): JSX.Element {
    const disabled = isSaved && !insightChanged
    const saveAsAvailable = isSaved && !addingToDashboard

    return saveUnder ? (
        <LemonButton
            type="primary"
            onClick={() => saveUnder()}
            data-attr="insight-save-under-button"
            disabled={disabled}
            loading={!disabled && insightSaving}
        >
            {disabled ? 'No changes to be saved' : 'Save to...'}
        </LemonButton>
    ) : (
        <LemonButton
            type="primary"
            onClick={() => saveInsight(true)}
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
                                    onClick={() => saveInsight(false)}
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
            {disabled ? 'No changes to be saved' : addingToDashboard ? 'Save & add to dashboard' : 'Save'}
        </LemonButton>
    )
}
