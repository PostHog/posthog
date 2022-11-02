import { useActions, useValues } from 'kea'
import { editFiltersLogic } from 'scenes/insights/filters/EditFilters/editFiltersLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { LemonButton } from 'lib/components/LemonButton'
import { Drawer } from 'lib/components/Drawer'
import { LemonTextArea } from 'lib/components/LemonTextArea/LemonTextArea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export function EditFilters(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { insightProps } = useValues(insightLogic)
    const { setFilters } = useActions(insightLogic)
    const { filters, editOpen, editText } = useValues(editFiltersLogic(insightProps))
    const { openEditFilters, closeEditFilters, setEditText } = useActions(editFiltersLogic(insightProps))

    if (!featureFlags[FEATURE_FLAGS.JSON_FILTERS]) {
        return null
    }

    let invalidJSON = false
    try {
        JSON.parse(editText)
    } catch (e) {
        invalidJSON = true
    }

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
                <Drawer
                    visible={editOpen}
                    onClose={closeEditFilters}
                    width={440}
                    footer={
                        <div className="flex space-x-2">
                            <LemonButton
                                type="primary"
                                onClick={() => setFilters(JSON.parse(editText))}
                                disabled={invalidJSON}
                                tooltip={invalidJSON ? 'Invalid JSON' : null}
                            >
                                Update
                            </LemonButton>
                            <LemonButton type="secondary" onClick={closeEditFilters}>
                                Cancel
                            </LemonButton>
                        </div>
                    }
                >
                    <LemonTextArea value={editText} onChange={(val) => setEditText(val)} />
                    {invalidJSON ? <div className="text-red">Invalid JSON</div> : null}
                </Drawer>
            ) : null}
        </>
    )
}
