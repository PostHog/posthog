import { useActions, useValues } from 'kea'
import { entityFilterLogic } from 'scenes/insights/ActionFilter/entityFilterLogic'
import React, { useEffect, useRef } from 'react'
import { InsightType, ViewType } from '~/types'
import { Button, Input, Modal } from 'antd'
import { getDisplayNameFromEntityFilter } from 'scenes/insights/utils'
import { renameModalLogic } from 'scenes/insights/ActionFilter/renameModalLogic'
import { InputFocusOptions } from 'antd/lib/input/Input'

interface RenameModalProps {
    typeKey: string
    view?: InsightType
}

export function RenameModal({ typeKey, view }: RenameModalProps): JSX.Element {
    const { selectedFilter, modalVisible } = useValues(entityFilterLogic)
    const { renameFilter, hideModal } = useActions(entityFilterLogic)

    const logic = renameModalLogic({ typeKey, filter: selectedFilter })
    const { name } = useValues(logic)
    const { setName } = useActions(logic)

    const ref = useRef<Input | null>(null)
    useSelectAllText(ref, { cursor: 'all' }, [modalVisible])

    const title = `Rename ${view === ViewType.FUNNELS ? 'funnel step' : 'graph series'}`

    return (
        <Modal
            data-attr="filter-rename-modal"
            visible={modalVisible}
            title={title}
            footer={
                <>
                    <Button type="link" onClick={hideModal}>
                        Cancel
                    </Button>
                    <Button type="primary" onClick={() => renameFilter(name)}>
                        {title}
                    </Button>
                </>
            }
            onCancel={hideModal}
        >
            Query steps can be renamed to provide a more meaningful label for your insight. Renamed steps are also shown
            on dashboards.
            <br />
            <div className="l4 mt-05 mb-05">Name</div>
            <Input
                ref={ref}
                value={name}
                onPressEnter={() => renameFilter(name)}
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

function useSelectAllText(
    ref: React.MutableRefObject<Input | null>,
    options: InputFocusOptions,
    dependencies: any[] = []
): void {
    // Hacky setTimeout is needed to select all text on modal open
    // https://github.com/ant-design/ant-design/issues/8668#issuecomment-352955313
    useEffect(
        () => {
            const autoFocusTimeout = setTimeout(() => {
                if (ref.current) {
                    ref.current?.focus(options)
                }
            }, 0)
            return () => clearTimeout(autoFocusTimeout)
        },

        dependencies
    )
}
