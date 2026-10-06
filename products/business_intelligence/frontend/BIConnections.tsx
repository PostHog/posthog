import { BindLogic, useMountedLogic, useValues } from 'kea'

import { BIConnectionGroup } from 'products/business_intelligence/frontend/BIConnectionGroup'
import { biConnectionsLogic } from 'products/business_intelligence/frontend/biConnectionsLogic'
import { biEditorLogic } from 'products/business_intelligence/frontend/biEditorLogic'

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
