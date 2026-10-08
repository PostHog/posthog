import { useActions } from 'kea'

import { IconChevronRight, IconDatabase } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { biConnectionsLogic } from 'products/business_intelligence/frontend/biConnectionsLogic'
import { BIConnection } from 'products/business_intelligence/frontend/biConnectionTree'
import { BIDataPaneSection } from 'products/business_intelligence/frontend/BIDataPaneSection'

export function BIConnectionGroup({ connections }: { connections: BIConnection[] }): JSX.Element | null {
    const { toggleConnection, hydrateTableFields } = useActions(biConnectionsLogic)
    if (!connections.length) {
        return null
    }
    return (
        <div className="flex min-w-0 flex-col" data-attr="bi-editor-connections">
            {connections.map((connection) => (
                <div key={connection.id} className="min-w-0">
                    <LemonButton
                        type="tertiary"
                        size="xxsmall"
                        fullWidth
                        truncate
                        icon={<IconChevronRight className={cn(connection.expanded && 'rotate-90')} />}
                        onClick={() => toggleConnection(connection.id, connection.tableName)}
                        aria-expanded={connection.expanded}
                        data-attr="bi-editor-connection"
                        tooltip={connection.path.join('.')}
                    >
                        <IconDatabase className="mr-1 shrink-0 text-brand-blue" />
                        <span className="truncate">{connection.name}</span>
                    </LemonButton>
                    {connection.expanded ? (
                        <div className="ml-2 min-w-0 border-l pl-1" data-attr="bi-editor-connection-fields">
                            {connection.state === 'loading' ? (
                                <div className="flex items-center gap-1 p-2 text-xs text-secondary">
                                    <Spinner /> Loading fields
                                </div>
                            ) : connection.state === 'error' ? (
                                <div className="flex flex-col items-start gap-1 p-2 text-xs">
                                    <span>Couldn't load fields.</span>
                                    <LemonButton
                                        type="secondary"
                                        size="xsmall"
                                        onClick={() =>
                                            connection.tableName && hydrateTableFields([connection.tableName])
                                        }
                                    >
                                        Retry
                                    </LemonButton>
                                </div>
                            ) : connection.state === 'missing' ? (
                                <span className="block p-2 text-xs text-secondary">
                                    Fields are unavailable. Check that the linked table still exists.
                                </span>
                            ) : (
                                <>
                                    <BIDataPaneSection
                                        fields={connection.fields.dimensions}
                                        path={connection.path}
                                        measure={false}
                                        emptyText="No matching dimensions"
                                    />
                                    <BIDataPaneSection
                                        fields={connection.fields.measures}
                                        path={connection.path}
                                        measure
                                        emptyText="No matching measures"
                                    />
                                    <BIConnectionGroup connections={connection.connections} />
                                </>
                            )}
                        </div>
                    ) : null}
                </div>
            ))}
        </div>
    )
}
