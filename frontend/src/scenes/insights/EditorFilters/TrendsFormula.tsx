import React, { useEffect, useState } from 'react'
import { EditorFilterProps } from '~/types'
import { useActions } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { Tooltip } from 'lib/components/Tooltip'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import { IconDelete, IconPlusMini } from 'lib/components/icons'

// When updating this regex, remember to update the regex with the same name in mixins/common.py
const ALLOWED_FORMULA_CHARACTERS = /^[a-zA-Z\ \-\*\^0-9\+\/\(\)\.]+$/

export function TrendsFormula({ filters, insightProps }: EditorFilterProps): JSX.Element {
    const { setFilters } = useActions(trendsLogic(insightProps))
    const [isUsingFormulas, setIsUsingFormulas] = useState(!!filters.formula)
    const formulaEnabled = (filters.events?.length || 0) + (filters.actions?.length || 0) > 0
    const [value, setValue] = useState(filters.formula)

    useEffect(() => {
        setValue(filters.formula)
    }, [filters.formula])

    return (
        <div className="flex items-center gap-2">
            {isUsingFormulas ? (
                <>
                    <LemonInput
                        className="flex-1"
                        placeholder="e.g. (A + B)/(A - B) * 100"
                        allowClear
                        autoFocus
                        value={value}
                        onChange={(value) => {
                            let changedValue = value.toLocaleUpperCase()
                            // Only allow typing of allowed characters
                            changedValue = changedValue
                                .split('')
                                .filter((d) => ALLOWED_FORMULA_CHARACTERS.test(d))
                                .join('')
                            setValue(changedValue)
                        }}
                        onBlur={() => setFilters({ formula: value })}
                        onPressEnter={() => setFilters({ formula: value })}
                    />

                    <LemonButton
                        className="shrink-0"
                        icon={<IconDelete />}
                        size="small"
                        status="primary-alt"
                        onClick={() => {
                            setIsUsingFormulas(false)
                            setFilters({ formula: undefined })
                        }}
                    />
                </>
            ) : (
                <Tooltip
                    title={!formulaEnabled ? 'Please add at least one graph series to use formulas' : undefined}
                    visible={formulaEnabled ? false : undefined}
                >
                    <LemonButton
                        onClick={() => setIsUsingFormulas(true)}
                        disabled={!formulaEnabled}
                        type="secondary"
                        icon={<IconPlusMini />}
                        data-attr="btn-add-formula"
                    >
                        Add formula
                    </LemonButton>
                </Tooltip>
            )}
        </div>
    )
}
