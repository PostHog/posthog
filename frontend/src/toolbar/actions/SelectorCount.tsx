import { IconPencil } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { querySelectorAllDeep } from 'query-selector-shadow-dom'
import { useMemo, useState } from 'react'

import { experimentsTabLogic } from '../experiments/experimentsTabLogic'

interface SelectorCountProps {
    selector: string | null
    variant: string
    transformIndex: number
}

export function SelectorCount({ selector, variant, transformIndex }: SelectorCountProps): JSX.Element | null {
    const { inspectElementSelected } = useActions(experimentsTabLogic)

    const [editSelectorOpen, setEditSelectorOpen] = useState(false)
    const [editSelectorValue, setEditSelectorValue] = useState('')

    const [matches, selectorError] = useMemo(() => {
        let _selectorError = false
        let _matches = 0
        if (selector) {
            try {
                _matches = querySelectorAllDeep(selector).length
            } catch {
                _selectorError = true
            }
        }
        return [_matches, _selectorError]
    }, [selector])

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

    return selector === null ? null : (
        <>
            <small className={`float-right flex items-center gap-1 ${selectorError && 'text-danger'}`}>
                {selectorError ? 'Invalid selector' : `Matches ${matches} element${matches === 1 ? '' : 's'}`}
                <LemonButton
                    size="xsmall"
                    icon={<IconPencil />}
                    onClick={(e) => {
                        e.stopPropagation()
                        setEditSelectorValue(selector)
                        setEditSelectorOpen(true)
                    }}
                />
            </small>
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
