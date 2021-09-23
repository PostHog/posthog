import { useActions, useValues } from 'kea'
import { entityFilterLogic } from 'scenes/insights/ActionFilter/entityFilterLogic'
import React, { useEffect, useState } from 'react'
import { EntityFilter } from '~/types'
import { Button, Input, Modal } from 'antd'
import { getDisplayNameFromEntityFilter } from 'scenes/insights/utils'

interface Props {
    visible: boolean
    setModalOpen: (state: boolean) => void
}

export function FilterRenameModal({ visible, setModalOpen }: Props): JSX.Element {
    const { selectedFilter } = useValues(entityFilterLogic)
    const { renameFilter, selectFilter } = useActions(entityFilterLogic)

    const [name, setName] = useState(getDisplayNameFromEntityFilter(selectedFilter) ?? '')

    useEffect(() => {
        setName(getDisplayNameFromEntityFilter(selectedFilter) ?? '')
    }, [selectedFilter])

    const onRename = (): void => {
        renameFilter({ ...selectedFilter, custom_name: name } as EntityFilter)
        setModalOpen(false)
    }

    return (
        <Modal
            data-attr="filter-rename-modal"
            visible={visible}
            title="Rename query step"
            footer={
                <>
                    <Button type="link" onClick={() => setModalOpen(false)}>
                        Cancel
                    </Button>
                    <Button type="primary" onClick={onRename}>
                        Rename query step
                    </Button>
                </>
            }
            onCancel={() => {
                setModalOpen(false)
                selectFilter(null)
            }}
        >
            Query steps can be renamed to provide a more meaningful label for your insight. Renamed steps are also shown
            on dashboards.
            <br />
            <div className="l4 mt-05 mb-05">Name</div>
            <Input
                value={name}
                onPressEnter={onRename}
                onChange={(e) => setName(e.target.value)}
                suffix={
                    <span className="text-muted-alt">
                        {getDisplayNameFromEntityFilter(selectedFilter, false) ?? ''}
                    </span>
                }
            />
        </Modal>
    )
}
