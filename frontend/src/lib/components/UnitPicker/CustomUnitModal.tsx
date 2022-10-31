import { FilterType } from '~/types'
import { RefCallback, useEffect, useState } from 'react'
import { LemonModal } from 'lib/components/LemonModal'
import { LemonButton } from 'lib/components/LemonButton'
import { PureField } from 'lib/forms/Field'
import { capitalizeFirstLetter } from 'lib/utils'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'
import { HandleUnitChange } from 'lib/components/UnitPicker/UnitPicker'

function chooseFormativeElement(formativeElement: 'prefix' | 'postfix' | null, filters: Partial<FilterType>): string {
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
    overlayRef: RefCallback<HTMLDivElement> // if an open pop up should not close when this is clicked on
}): JSX.Element | null {
    const [localFormativeElement, setLocalFormativeElement] = useState<string>(
        chooseFormativeElement(formativeElement, filters)
    )
    useEffect(() => {
        setLocalFormativeElement(chooseFormativeElement(formativeElement, filters))
    }, [formativeElement])

    if (formativeElement === null) {
        return null
    }

    return (
        <LemonModal
            overlayRef={overlayRef}
            isOpen={isOpen}
            onClose={onClose}
            title={`Custom ${formativeElement}`}
            footer={
                <>
                    <LemonButton type="primary" onClick={() => onSave({ [formativeElement]: localFormativeElement })}>
                        Save
                    </LemonButton>
                </>
            }
        >
            <PureField
                label={`${capitalizeFirstLetter(formativeElement)}:`}
                help={
                    <>
                        A {formativeElement} of <strong>{localFormativeElement || '$'}</strong> would mean `123.45`
                        would be displayed{' '}
                        <strong>
                            {formativeElement === 'prefix' ? localFormativeElement || '$' : ''}123.45
                            {formativeElement === 'postfix' ? localFormativeElement || '$' : ''}
                        </strong>
                    </>
                }
            >
                <LemonInput value={localFormativeElement} onChange={setLocalFormativeElement} />
            </PureField>
        </LemonModal>
    )
}
