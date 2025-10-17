import { actions, kea, listeners, path, reducers } from 'kea'

import type { unitPickerModalLogicType } from './unitPickerModalLogicType'

export interface CustomUnitModalData {
    type: 'prefix' | 'postfix'
    currentValue: string
    callback: (value: string) => void
}

export interface UnitPickerModalLogicType {
    actions: {
        showCustomUnitModal: (data: CustomUnitModalData) => { data: CustomUnitModalData }
        hideCustomUnitModal: () => void
        applyCustomUnit: (value: string) => { value: string }
    }
    values: {
        customUnitModalData: CustomUnitModalData | null
        isCustomUnitModalOpen: boolean
    }
}

export const unitPickerModalLogic = kea<unitPickerModalLogicType>([
    path(['lib', 'components', 'UnitPicker', 'unitPickerModalLogic']),
    actions({
        showCustomUnitModal: (data: CustomUnitModalData) => ({ data }),
        hideCustomUnitModal: true,
        applyCustomUnit: (value: string) => ({ value }),
    }),
    reducers({
        customUnitModalData: [
            null as CustomUnitModalData | null,
            {
                showCustomUnitModal: (_, { data }) => data,
                hideCustomUnitModal: () => null,
            },
        ],
        isCustomUnitModalOpen: [
            false,
            {
                showCustomUnitModal: () => true,
                hideCustomUnitModal: () => false,
                applyCustomUnit: () => false,
            },
        ],
    }),
    listeners(({ values }) => ({
        applyCustomUnit: ({ value }: { value: string }) => {
            if (values.customUnitModalData?.callback) {
                values.customUnitModalData.callback(value)
            }
        },
    })),
])
