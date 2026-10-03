import { BindLogic, useMountedLogic, useValues } from 'kea'

import { biEditorLogic } from 'scenes/data-warehouse/editor/bi/biEditorLogic'

import { BIConnectionGroup } from './BIConnectionGroup'
import { biConnectionsLogic } from './biConnectionsLogic'

export function BIConnections(): JSX.Element {
    const biLogic = useMountedLogic(biEditorLogic)
    const logicProps = { tabId: biLogic.props.tabId }
    const { filteredConnections } = useValues(biConnectionsLogic(logicProps))
    return (
        <BindLogic logic={biConnectionsLogic} props={logicProps}>
            {filteredConnections.length ? (
                <div className="px-2 pb-1 pt-2 text-xs font-semibold text-secondary">Connections</div>
            ) : null}
            <BIConnectionGroup connections={filteredConnections} />
        </BindLogic>
    )
}
