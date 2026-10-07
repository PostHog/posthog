import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { entityFilterLogic } from 'scenes/insights/filters/ActionFilter/entityFilterLogic'
import { renameModalLogic } from 'scenes/insights/filters/ActionFilter/renameModalLogic'
import { getDisplayNameFromEntityNode } from 'scenes/insights/utils'

import { InsightType } from '~/types'

interface RenameModalProps {
    typeKey: string
    view?: InsightType
}

export function RenameModal({ typeKey, view }: RenameModalProps): JSX.Element {
    const { selectedSeries, modalVisible } = useValues(entityFilterLogic)
    const { renameSeries, hideModal } = useActions(entityFilterLogic)

    const selectedNode = selectedSeries?.node ?? null
    const logic = renameModalLogic({ typeKey, node: selectedNode })
    const { name } = useValues(logic)
    const { setName } = useActions(logic)

    const title = `Rename ${view === InsightType.FUNNELS ? 'funnel step' : 'graph series'}`

    return (
        <LemonModal
            data-attr="filter-rename-modal"
            isOpen={modalVisible}
            title={title}
            width={520}
            forceAbovePopovers={true}
            footer={
                <>
                    <LemonButton type="secondary" onClick={hideModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" onClick={() => renameSeries(name)}>
                        {title}
                    </LemonButton>
                </>
            }
            onClose={hideModal}
        >
            Query series/steps can be renamed to provide a more{' '}
            <strong>meaningful label for you and your team members</strong>. Custom names are also shown on dashboards.
            <br />
            <div className="l4 mt-2 mb-2">Name</div>
            <LemonInput
                value={name}
                onPressEnter={() => renameSeries(name)}
                onChange={(value) => setName(value)}
                suffix={
                    <span
                        className="text-secondary truncate max-w-[200px]"
                        title={(selectedNode ? getDisplayNameFromEntityNode(selectedNode, false) : null) ?? ''}
                    >
                        {(selectedNode ? getDisplayNameFromEntityNode(selectedNode, false) : null) ?? ''}
                    </span>
                }
                autoFocus
                onFocus={(e) => e.target.select()}
            />
        </LemonModal>
    )
}
