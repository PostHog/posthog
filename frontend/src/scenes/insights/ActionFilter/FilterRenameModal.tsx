import { useActions, useValues } from 'kea'
import { entityFilterLogic } from 'scenes/insights/ActionFilter/entityFilterLogic'
import React, { useEffect, useRef, useState } from 'react'
import { EntityFilter, InsightType, ViewType } from '~/types'
import { Button, Input, Modal } from 'antd'
import { getDisplayNameFromEntityFilter } from 'scenes/insights/utils'

interface Props {
    visible: boolean
    setModalOpen: (state: boolean) => void
    view?: InsightType
}

export function FilterRenameModal({ visible, setModalOpen, view }: Props): JSX.Element {
    const ref = useRef<Input | null>(null)
    const { selectedFilter } = useValues(entityFilterLogic)
    const { renameFilter, selectFilter } = useActions(entityFilterLogic)

    const [name, setName] = useState(getDisplayNameFromEntityFilter(selectedFilter) ?? '')

    useEffect(() => {
        setName(getDisplayNameFromEntityFilter(selectedFilter) ?? '')
    }, [selectedFilter])

    // Hacky setTimeout is needed - https://github.com/ant-design/ant-design/issues/8668#issuecomment-352955313
    useEffect(() => {
        const autoFocusTimeout = setTimeout(() => {
            if (visible && ref.current) {
                ref.current?.focus({
                    cursor: 'all',
                })
            }
        }, 0)
        return () => clearTimeout(autoFocusTimeout)
    }, [visible])

    const onRename = (): void => {
        renameFilter({ ...selectedFilter, custom_name: name } as EntityFilter)
        setModalOpen(false)
    }

    const title = `Rename ${view === ViewType.FUNNELS ? 'funnel step' : 'graph series'}`

    return (
        <Modal
            data-attr="filter-rename-modal"
            visible={visible}
            title={title}
            footer={
                <>
                    <Button type="link" onClick={() => setModalOpen(false)}>
                        Cancel
                    </Button>
                    <Button type="primary" onClick={onRename}>
                        {title}
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
                ref={ref}
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
