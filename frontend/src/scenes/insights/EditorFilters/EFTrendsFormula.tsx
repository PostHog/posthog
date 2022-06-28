import React, { useState } from 'react'
import { EditorFilterProps } from '~/types'
import { useActions } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { Tooltip } from 'lib/components/Tooltip'
import { CloseButton } from 'lib/components/CloseButton'
import { Formula } from 'scenes/insights/filters/Formula'
import { LemonButton } from '@posthog/lemon-ui'
import { IconPlusMini } from 'lib/components/icons'

export function EFTrendsFormula({ filters, insightProps }: EditorFilterProps): JSX.Element {
    const { setFilters } = useActions(trendsLogic(insightProps))
    const [isUsingFormulas, setIsUsingFormulas] = useState(!!filters.formula)

    const formulaEnabled = (filters.events?.length || 0) + (filters.actions?.length || 0) > 0

    return (
        <>
            {isUsingFormulas ? (
                <div className="flex items-center gap-05">
                    <CloseButton
                        onClick={() => {
                            setIsUsingFormulas(false)
                            setFilters({ formula: undefined })
                        }}
                    />
                    <Formula
                        filters={filters}
                        onChange={(formula: string): void => {
                            setFilters({ formula })
                        }}
                        autoFocus
                        allowClear={false}
                    />
                </div>
            ) : (
                <Tooltip
                    title={!formulaEnabled ? 'Please add at least one graph series to use formulas' : undefined}
                    visible={formulaEnabled ? false : undefined}
                >
                    <LemonButton
                        onClick={() => setIsUsingFormulas(true)}
                        disabled={!formulaEnabled}
                        type="secondary"
                        icon={<IconPlusMini color="var(--primary)" />}
                        data-attr="btn-add-formula"
                    >
                        Add formula
                    </LemonButton>
                </Tooltip>
            )}
        </>
    )
}
