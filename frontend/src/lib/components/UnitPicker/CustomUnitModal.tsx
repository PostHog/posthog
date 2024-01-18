import { HandleUnitChange } from 'lib/components/UnitPicker/UnitPicker'
import { PureField } from 'lib/forms/Field'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { capitalizeFirstLetter } from 'lib/utils'
import { RefCallback, useEffect, useState } from 'react'

import { TrendsFilter } from '~/queries/schema'

function chooseFormativeElementValue(
    formativeElement: 'prefix' | 'postfix' | null,
    trendsFilter: TrendsFilter | null | undefined
): string {
    if (formativeElement === 'prefix') {
        return trendsFilter?.aggregationAxisPrefix || ''
    }

    if (formativeElement === 'postfix') {
        return trendsFilter?.aggregationAxisPostfix || ''
    }

    return ''
}

type CustomUnitModalProps = {
    isOpen: boolean
    onSave: (hx: HandleUnitChange) => void
    formativeElement: 'prefix' | 'postfix' | null
    trendsFilter: TrendsFilter | null | undefined
    onClose: () => void
    overlayRef: RefCallback<HTMLDivElement>
}

export function CustomUnitModal({
    isOpen,
    onSave,
    formativeElement,
    trendsFilter,
    onClose,
    overlayRef,
}: CustomUnitModalProps): JSX.Element | null {
    const [localFormativeElementValue, setLocalFormativeElementValue] = useState<string>(
        chooseFormativeElementValue(formativeElement, trendsFilter)
    )
    useEffect(() => {
        setLocalFormativeElementValue(chooseFormativeElementValue(formativeElement, trendsFilter))
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
