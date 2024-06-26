import { useValues } from 'kea'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { useMemo } from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { QueryContext, QueryContextColumnComponent } from '~/queries/types'

import { ErrorTrackingFilters } from './ErrorTrackingFilters'
import { errorTrackingLogic } from './errorTrackingLogic'
import { errorTrackingSceneLogic } from './errorTrackingSceneLogic'
import { errorTrackingQuery } from './queries'

export const scene: SceneExport = {
    component: ErrorTrackingScene,
    logic: errorTrackingSceneLogic,
}

export function ErrorTrackingScene(): JSX.Element {
    const { order } = useValues(errorTrackingSceneLogic)
    const { dateRange, filterTestAccounts, filterGroup } = useValues(errorTrackingLogic)

    const query = useMemo(
        () => errorTrackingQuery({ order, dateRange, filterTestAccounts, filterGroup }),
        [order, dateRange, filterTestAccounts, filterGroup]
    )

    const context: QueryContext = {
        columns: {
            'any(properties) -- Error': {
                width: '50%',
                render: CustomGroupTitleColumn,
            },
        },
        showOpenEditorButton: false,
    }

    return (
        <div className="space-y-4">
            <ErrorTrackingFilters />
            <Query query={query} context={context} />
        </div>
    )
}

const CustomGroupTitleColumn: QueryContextColumnComponent = (props) => {
    const { value } = props
    const properties = JSON.parse(value as string)

    return (
        <LemonTableLink
            title={properties.$exception_type}
            description={<div className="line-clamp-1">{properties.$exception_message}</div>}
            to={urls.errorTrackingGroup(properties.$exception_type)}
        />
    )
}
