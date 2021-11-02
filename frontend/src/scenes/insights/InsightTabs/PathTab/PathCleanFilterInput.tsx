import React, { useState } from 'react'
import { PathCleanFilters } from 'lib/components/PathCleanFilters/PathCleanFilters'
import { Button, Row } from 'antd'
import { Popup } from 'lib/components/Popup/Popup'
import { PathRegexPopup } from 'lib/components/PathCleanFilters/PathCleanFilter'
import { PathCleanFilterToggle } from './PathCleanFilterToggle'
import { PlusCircleOutlined } from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import { pathsLogic } from 'scenes/paths/pathsLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

export function PathCleanFilterInput(): JSX.Element {
    const [open, setOpen] = useState(false)
    const { insightProps } = useValues(insightLogic)
    const { filter } = useValues(pathsLogic(insightProps))
    const { setFilter } = useActions(pathsLogic(insightProps))

    return (
        <>
            <PathCleanFilters
                style={{ paddingLeft: 10 }}
                pageKey="pathcleanfilters-local"
                pathCleaningFilters={filter.local_path_cleaning_filters || []}
                onChange={(newItem) => {
                    setFilter({
                        local_path_cleaning_filters: [...(filter.local_path_cleaning_filters || []), newItem],
                    })
                }}
                onRemove={(index) => {
                    const newState = (filter.local_path_cleaning_filters || []).filter((_, i) => i !== index)
                    setFilter({ local_path_cleaning_filters: newState })
                }}
            />
            <Row align="middle" justify="space-between">
                <Popup
                    visible={open}
                    placement={'bottom-end'}
                    fallbackPlacements={['bottom-start']}
                    onClickOutside={() => setOpen(false)}
                    overlay={
                        <PathRegexPopup
                            item={{}}
                            onClose={() => setOpen(false)}
                            onComplete={(newItem) => {
                                setFilter({
                                    local_path_cleaning_filters: [
                                        ...(filter.local_path_cleaning_filters || []),
                                        newItem,
                                    ],
                                })
                                setOpen(false)
                            }}
                        />
                    }
                >
                    {({ setRef }) => {
                        return (
                            <>
                                <Button
                                    ref={setRef}
                                    onClick={() => setOpen(!open)}
                                    className="new-prop-filter"
                                    data-attr={'new-prop-filter-' + 'pathcleanfilters-local'}
                                    type="link"
                                    style={{ paddingLeft: 0 }}
                                    icon={<PlusCircleOutlined />}
                                >
                                    {'Add Rule'}
                                </Button>
                            </>
                        )
                    }}
                </Popup>
                <PathCleanFilterToggle filters={filter} onChange={setFilter} />
            </Row>
        </>
    )
}
