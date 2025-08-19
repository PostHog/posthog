import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { capitalizeFirstLetter } from 'lib/utils'

import { unitPickerModalLogic } from './unitPickerModalLogic'

export function GlobalCustomUnitModal(): JSX.Element | null {
    const { isCustomUnitModalOpen, customUnitModalData } = useValues(unitPickerModalLogic)
    const { hideCustomUnitModal, applyCustomUnit } = useActions(unitPickerModalLogic)
    const [localValue, setLocalValue] = useState('')

    // Update local value when modal data changes
    useEffect(() => {
        if (customUnitModalData) {
            setLocalValue(customUnitModalData.currentValue)
        }
    }, [customUnitModalData])

    if (!isCustomUnitModalOpen || !customUnitModalData) {
        return null
    }

    const { type } = customUnitModalData

    return (
        <LemonModal
            isOpen={isCustomUnitModalOpen}
            onClose={hideCustomUnitModal}
            forceAbovePopovers={true}
            title={`Custom ${type}`}
            footer={
                <>
                    <LemonButton type="secondary" data-attr={`custom-${type}-cancel`} onClick={hideCustomUnitModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" onClick={() => applyCustomUnit(localValue)}>
                        Apply
                    </LemonButton>
                </>
            }
        >
            <LemonField.Pure
                label={`${capitalizeFirstLetter(type)}:`}
                help={
                    <>
                        With a {type} of "<strong>{localValue || '$'}</strong>", 123.45 will be displayed as "
                        <strong>
                            {type === 'prefix' ? localValue || '$' : ''}123.45
                            {type === 'postfix' ? localValue || '$' : ''}
                        </strong>
                        "
                    </>
                }
            >
                <LemonInput value={localValue} onChange={setLocalValue} autoFocus />
            </LemonField.Pure>
        </LemonModal>
    )
}
