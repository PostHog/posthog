import { LemonButton, LemonCollapse } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { DataTableNode } from '~/queries/schema/schema-general'
import { PersonsTabType } from '~/types'

interface ExceptionsPanelProps {
    exceptionsQuery: DataTableNode | null
    sessionId?: string
    distinctId?: string
}

export function ExceptionsPanel({ exceptionsQuery, sessionId, distinctId }: ExceptionsPanelProps): JSX.Element {
    return (
        <LemonCollapse
            className="bg-surface-primary"
            panels={[
                {
                    key: 'exceptions',
                    header: (
                        <>
                            Exceptions
                            {sessionId && <span className="text-muted-alt font-normal ml-1">(session)</span>}
                        </>
                    ),
                    content: (
                        <div>
                            {!exceptionsQuery ? (
                                <div className="text-muted-alt text-xs">No exceptions found</div>
                            ) : (
                                <div className="max-h-96 overflow-auto">
                                    <Query query={exceptionsQuery} filtersOverride={null} />
                                </div>
                            )}
                            {distinctId && (
                                <div className="mt-2 pt-2 border-t flex justify-end">
                                    <LemonButton
                                        type="tertiary"
                                        size="xsmall"
                                        to={`${urls.personByDistinctId(distinctId)}#activeTab=${PersonsTabType.EXCEPTIONS}`}
                                    >
                                        See all exceptions →
                                    </LemonButton>
                                </div>
                            )}
                        </div>
                    ),
                },
            ]}
        />
    )
}
