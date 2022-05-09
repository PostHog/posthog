import React, { useState } from 'react'
import { EditorFilterProps } from '~/types'
import { useActions } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { Tooltip } from 'lib/components/Tooltip'
import { PlusCircleOutlined } from '@ant-design/icons'
import { Button, Col, Row } from 'antd'
import { CloseButton } from 'lib/components/CloseButton'
import { Formula } from 'scenes/insights/InsightTabs/TrendTab/Formula'

export function EFTrendsFormula({ filters, insightProps }: EditorFilterProps): JSX.Element {
    const { setFilters } = useActions(trendsLogic(insightProps))
    const [isUsingFormulas, setIsUsingFormulas] = useState(!!filters.formula)

    const formulaEnabled = (filters.events?.length || 0) + (filters.actions?.length || 0) > 0

    return (
        <>
            {isUsingFormulas ? (
                <Row align="middle" gutter={4}>
                    <Col>
                        <CloseButton
                            onClick={() => {
                                setIsUsingFormulas(false)
                                setFilters({ formula: undefined })
                            }}
                        />
                    </Col>
                    <Col>
                        <Formula
                            filters={filters}
                            onChange={(formula: string): void => {
                                setFilters({ formula })
                            }}
                            autoFocus
                            allowClear={false}
                        />
                    </Col>
                </Row>
            ) : (
                <Tooltip
                    title={!formulaEnabled ? 'Please add at least one graph series to use formulas' : undefined}
                    visible={formulaEnabled ? false : undefined}
                >
                    <Button
                        onClick={() => setIsUsingFormulas(true)}
                        disabled={!formulaEnabled}
                        type="link"
                        style={{ paddingLeft: 0 }}
                        icon={<PlusCircleOutlined />}
                        data-attr="btn-add-formula"
                    >
                        Add formula
                    </Button>
                </Tooltip>
            )}
        </>
    )
}
