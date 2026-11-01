import { useContext, useEffect, useState } from 'react'

import { IconPencil } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { SelectorCountContext } from '~/toolbar/shared/actions/SelectorCountContext'
import { useWebExperimentEditor } from '~/toolbar/shared/experiments/webExperimentEditorContext'

interface SelectorEditorProps {
    selector: string | null
    variant: string
    transformIndex: number
}

export function SelectorEditor({ selector, variant, transformIndex }: SelectorEditorProps): JSX.Element {
    const { setTransformationSelector } = useWebExperimentEditor()
    const counter = useContext(SelectorCountContext)

    const [editSelectorOpen, setEditSelectorOpen] = useState(false)
    const [editSelectorValue, setEditSelectorValue] = useState('')

    useEffect(() => {
        if (editSelectorOpen && editSelectorValue) {
            counter.request(editSelectorValue)
        }
    }, [editSelectorOpen, editSelectorValue, counter])
    // posthog-js applies web experiments with document.querySelectorAll, which skips shadow roots.
    const isValidSelector = !!editSelectorValue && !!counter.count(editSelectorValue, 'document')

    return (
        <>
            <LemonButton
                size="xsmall"
                icon={<IconPencil />}
                tooltip="Edit selector"
                onClick={(e) => {
                    e.stopPropagation()
                    setEditSelectorValue(selector ?? '')
                    setEditSelectorOpen(true)
                }}
            />
            <LemonModal
                isOpen={editSelectorOpen}
                onClose={() => setEditSelectorOpen(false)}
                title="Edit selector"
                footer={
                    <>
                        <LemonButton onClick={() => setEditSelectorOpen(false)}>Cancel</LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={() => {
                                setEditSelectorOpen(false)
                                setTransformationSelector(variant, transformIndex, editSelectorValue)
                            }}
                            disabledReason={
                                !isValidSelector
                                    ? 'Please enter a valid selector. Element not found on page.'
                                    : undefined
                            }
                        >
                            Save
                        </LemonButton>
                    </>
                }
            >
                <LemonInput value={editSelectorValue} onChange={(value) => setEditSelectorValue(value)} />
            </LemonModal>
        </>
    )
}
