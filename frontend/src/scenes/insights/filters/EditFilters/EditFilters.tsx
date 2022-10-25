import { useActions, useValues } from 'kea'
import { editFiltersLogic } from 'scenes/insights/filters/EditFilters/editFiltersLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { LemonButton } from 'lib/components/LemonButton'
import { Drawer } from 'lib/components/Drawer'
import { LemonTextArea } from 'lib/components/LemonTextArea/LemonTextArea'

export function EditFilters(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { filters, editOpen, editText } = useValues(editFiltersLogic(insightProps))
    const { openEditFilters, closeEditFilters, setEditText } = useActions(editFiltersLogic(insightProps))

    return (
        <>
            <LemonButton
                size="small"
                type="tertiary"
                tooltip="Edit filters as code"
                onClick={() => {
                    if (editOpen) {
                        closeEditFilters()
                    } else {
                        openEditFilters(filters)
                    }
                }}
            >
                <code>&lt;/&gt;</code>
            </LemonButton>
            {editOpen ? (
                <Drawer visible={editOpen} onClose={closeEditFilters} width={440}>
                    <LemonTextArea value={editText} onChange={(val) => setEditText(val)} />
                </Drawer>
            ) : null}
        </>
    )
}
