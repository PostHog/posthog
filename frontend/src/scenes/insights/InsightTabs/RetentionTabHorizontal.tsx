import React, { useState, useRef } from 'react'
import { useValues, useActions } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { ActionFilterDropdown } from '../ActionFilter/ActionFilterRow/ActionFilterDropdown'
import { entityFilterLogic } from '../ActionFilter/entityFilterLogic'

import { DownOutlined, InfoCircleOutlined } from '@ant-design/icons'
import { retentionTableLogic, dateOptions, retentionOptionDescriptions } from 'scenes/retention/retentionTableLogic'
import { Button, Select, Tooltip, Row, Col, Skeleton } from 'antd'

import { FilterType, RetentionType } from '~/types'
import { TestAccountFilter } from '../TestAccountFilter'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import './RetentionTab.scss'
import { RETENTION_FIRST_TIME, RETENTION_RECURRING } from 'lib/constants'
import useBreakpoint from 'antd/lib/grid/hooks/useBreakpoint'
import { IconExternalLink } from 'lib/components/icons'

export function RetentionTabHorizontal(): JSX.Element {
    const node = useRef<HTMLElement>(null)
    const returningNode = useRef<HTMLElement>(null)
    const [open, setOpen] = useState<boolean>(false)
    const [returningOpen, setReturningOpen] = useState<boolean>(false)
    const { filters, actionsLookup, filtersLoading } = useValues(retentionTableLogic({ dashboardItemId: null }))
    const { setFilters } = useActions(retentionTableLogic({ dashboardItemId: null }))

    const screens = useBreakpoint()
    const isSmallScreen = screens.xs || (screens.sm && !screens.md)

    const entityLogic = entityFilterLogic({
        setFilters: (filters: FilterType) => {
            if (filters.events && filters.events.length > 0) {
                setFilters({ target_entity: filters.events[0] })
            } else if (filters.actions && filters.actions.length > 0) {
                setFilters({ target_entity: filters.actions[0] })
            } else {
                setFilters({ target_entity: null })
            }
            setOpen(false)
        },
        filters: filters.target_entity,
        typeKey: 'retention-table',
        singleMode: true,
    })

    const entityLogicReturning = entityFilterLogic({
        setFilters: (filters: FilterType) => {
            if (filters.events && filters.events.length > 0) {
                setFilters({ returning_entity: filters.events[0] })
            } else if (filters.actions && filters.actions.length > 0) {
                setFilters({ returning_entity: filters.actions[0] })
            } else {
                setFilters({ returning_entity: null })
            }
            setReturningOpen(false)
        },
        filters: filters.returning_entity,
        typeKey: 'retention-table-returning',
        singleMode: true,
    })

    const selectedRetainingEvent =
        filters.returning_entity?.name ||
        (filters.returning_entity.id && actionsLookup[filters.returning_entity.id]) ||
        'Select action'

    const selectedCohortizingEvent =
        filters.target_entity?.name ||
        (filters.target_entity.id && actionsLookup[filters.target_entity.id]) ||
        'Select action'

    // TODO: Update constant in retentionTableLogic.ts when releasing 4050
    const retentionOptions = {
        [`${RETENTION_FIRST_TIME}`]: 'for the first time',
        [`${RETENTION_RECURRING}`]: 'recurringly',
    }

    return (
        <div data-attr="retention-tab" className="retention-tab">
            <Row gutter={16}>
                <Col md={16} xs={24}>
                    <Row gutter={8} align="middle" className="mt">
                        <Col>
                            Showing <b>Unique users</b> who did
                        </Col>
                        <Col>
                            <Button ref={node} data-attr="retention-action" onClick={() => setOpen(!open)}>
                                <PropertyKeyInfo value={selectedCohortizingEvent} disablePopover />
                                <DownOutlined
                                    className="svg-fix"
                                    style={{ marginRight: '-6px', marginTop: 2, color: '#bdbdbd', fontSize: '1.3em' }}
                                />
                            </Button>
                            <ActionFilterDropdown
                                open={open}
                                logic={entityLogic as any}
                                openButtonRef={node}
                                onClose={() => setOpen(false)}
                            />
                        </Col>
                        <Col>
                            <div style={{ display: '-webkit-inline-box', flexWrap: 'wrap' }}>
                                <Select
                                    value={retentionOptions[filters.retention_type]}
                                    onChange={(value): void => setFilters({ retention_type: value as RetentionType })}
                                    dropdownMatchSelectWidth={false}
                                >
                                    {Object.entries(retentionOptions).map(([key, value]) => (
                                        <Select.Option key={key} value={key}>
                                            {value}
                                            <Tooltip placement="right" title={retentionOptionDescriptions[key]}>
                                                <InfoCircleOutlined className="info-indicator" />
                                            </Tooltip>
                                        </Select.Option>
                                    ))}
                                </Select>
                            </div>
                        </Col>
                        <Col>grouped by</Col>
                        <Col>
                            <Select
                                value={filters.period}
                                onChange={(value): void => setFilters({ period: value })}
                                dropdownMatchSelectWidth={false}
                            >
                                {dateOptions.map((period) => (
                                    <Select.Option key={period} value={period}>
                                        {period}
                                    </Select.Option>
                                ))}
                            </Select>
                        </Col>
                    </Row>
                    <Row gutter={8} align="middle" className="mt">
                        <Col>... who then came back and did</Col>
                        <Col>
                            <Button
                                ref={returningNode}
                                data-attr="retention-returning-action"
                                onClick={(): void => setReturningOpen(!returningOpen)}
                            >
                                <PropertyKeyInfo value={selectedRetainingEvent} disablePopover />
                                <DownOutlined
                                    className="svg-fix"
                                    style={{ marginRight: '-6px', marginTop: 2, color: '#bdbdbd', fontSize: '1.3em' }}
                                />
                            </Button>
                            <ActionFilterDropdown
                                open={returningOpen}
                                logic={entityLogicReturning as any}
                                openButtonRef={returningNode}
                                onClose={() => setReturningOpen(false)}
                            />
                        </Col>
                    </Row>
                    <Row>
                        <Col>
                            <p className="text-muted mt">
                                Want to learn more about retention?{' '}
                                <a
                                    href="https://posthog.com/docs/features/retention?utm_campaign=learn-more-horizontal&utm_medium=in-product"
                                    target="_blank"
                                    rel="noopener"
                                    style={{ display: 'inline-flex', alignItems: 'center' }}
                                >
                                    Go to docs
                                    <IconExternalLink style={{ marginLeft: 4 }} />
                                </a>
                            </p>
                        </Col>
                    </Row>
                </Col>
                <Col md={8} xs={24} style={{ marginTop: isSmallScreen ? '2rem' : 0 }}>
                    <h4 className="secondary">Global Filters</h4>
                    {filtersLoading ? (
                        <Skeleton active paragraph={{ rows: 1 }} />
                    ) : (
                        <>
                            <PropertyFilters pageKey="insight-retention" />
                            <TestAccountFilter filters={filters} onChange={setFilters} />
                        </>
                    )}
                </Col>
            </Row>
        </div>
    )
}
