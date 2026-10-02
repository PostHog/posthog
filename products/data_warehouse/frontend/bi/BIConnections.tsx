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
            <BIConnectionGroup connections={filteredConnections} />
        </BindLogic>
    )
}
