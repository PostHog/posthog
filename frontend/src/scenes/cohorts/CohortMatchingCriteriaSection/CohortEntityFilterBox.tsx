import React from 'react'
import { DownOutlined } from '@ant-design/icons'
import { ActionFilter, EntityFilter } from '~/types'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Button } from 'antd'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { Popup } from 'lib/components/Popup/Popup'

export function CohortEntityFilterBox({
    open = false,
    onSelect,
    onOpen,
    onClose,
    filter,
}: {
    open: boolean
    onSelect: (type: TaxonomicFilterGroupType, id: string | number, name: string) => void
    onOpen: () => void
    onClose: () => void
    filter: Partial<EntityFilter> | Partial<ActionFilter>
}): JSX.Element | null {
    return (
        <Popup
            overlay={
                <TaxonomicFilter
                    value={filter.name ?? undefined}
                    onChange={(taxonomicGroup, changedValue, item) => {
                        onSelect(taxonomicGroup.type, changedValue, item?.name)
                    }}
                    onClose={onClose}
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions]}
                />
            }
            visible={open}
            onClickOutside={onClose}
        >
            {({ setRef }) => (
                <Button
                    data-attr="edit-cohort-entity-filter"
                    onClick={onOpen}
                    ref={setRef}
                    className="full-width"
                    style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                    }}
                >
                    <span className="text-overflow" style={{ maxWidth: '100%' }}>
                        <EntityFilterInfo filter={filter as EntityFilter | ActionFilter} />
                    </span>
                    <DownOutlined style={{ fontSize: 10 }} />
                </Button>
            )}
        </Popup>
    )
}
