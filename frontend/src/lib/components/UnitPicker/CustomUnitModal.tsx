import { FilterType, TrendsFilterType } from '~/types'
import { RefCallback, useEffect, useState } from 'react'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { PureField } from 'lib/forms/Field'
import { capitalizeFirstLetter } from 'lib/utils'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { HandleUnitChange } from 'lib/components/UnitPicker/UnitPicker'

function chooseFormativeElementValue(
    formativeElement: 'prefix' | 'postfix' | null,
    filters: Partial<TrendsFilterType>
): string {
    if (formativeElement === 'prefix') {
        return filters.aggregation_axis_prefix || ''
    }

    if (formativeElement === 'postfix') {
        return filters.aggregation_axis_postfix || ''
    }

    return ''
}

export function CustomUnitModal({
    isOpen,
    onSave,
    formativeElement,
    filters,
    onClose,
    overlayRef,
}: {
    isOpen: boolean
    onSave: (hx: HandleUnitChange) => void
    formativeElement: 'prefix' | 'postfix' | null
    filters: Partial<FilterType>
    onClose: () => void
    overlayRef: RefCallback<HTMLDivElement>
}): JSX.Element | null {
    const [localFormativeElementValue, setLocalFormativeElementValue] = useState<string>(
        chooseFormativeElementValue(formativeElement, filters)
    )
    useEffect(() => {
        setLocalFormativeElementValue(chooseFormativeElementValue(formativeElement, filters))
    }, [formativeElement])

    if (formativeElement === null) {
        return null
    }

    return (
        <LemonModal
            overlayRef={overlayRef}
            isOpen={isOpen}
            onClose={onClose}
            forceAbovePopovers={true}
            title={`Custom ${formativeElement}`}
            footer={
                <>
                    <LemonButton type="secondary" data-attr="custom-prefix-cancel" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={() => onSave({ [formativeElement]: localFormativeElementValue })}
                    >
                        Apply
                    </LemonButton>
                </>
            }
        >
            <PureField
                label={`${capitalizeFirstLetter(formativeElement)}:`}
                help={
                    <>
                        With a {formativeElement} of "<strong>{localFormativeElementValue || '$'}</strong>", 123.45 will
                        be displayed as "
                        <strong>
                            {formativeElement === 'prefix' ? localFormativeElementValue || '$' : ''}123.45
                            {formativeElement === 'postfix' ? localFormativeElementValue || '$' : ''}
                        </strong>
                        "
                    </>
                }
            >
                <LemonInput value={localFormativeElementValue} onChange={setLocalFormativeElementValue} autoFocus />
            </PureField>
        </LemonModal>
    )
}
