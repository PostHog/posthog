import { useActions } from 'kea'
import { useMemo, useState } from 'react'

import { IconPencil } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { experimentsTabLogic } from './experimentsTabLogic'

interface SelectorEditorProps {
    selector: string | null
    variant: string
    transformIndex: number
}

export function SelectorEditor({ selector, variant, transformIndex }: SelectorEditorProps): JSX.Element {
    const { inspectElementSelected } = useActions(experimentsTabLogic)

    const [editSelectorOpen, setEditSelectorOpen] = useState(false)
    const [editSelectorValue, setEditSelectorValue] = useState('')

    const isValidSelector = useMemo(() => {
        if (!editSelectorValue) {
            return false
        }
        try {
            return !!document.querySelector(editSelectorValue)
        } catch {
            return false
        }
    }, [editSelectorValue])

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
                                inspectElementSelected(
                                    document.querySelector(editSelectorValue) as HTMLElement,
                                    variant,
                                    transformIndex,
                                    editSelectorValue
                                )
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
