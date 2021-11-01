import { kea, useValues } from 'kea'
import React from 'react'
import { Lettermark } from 'lib/components/Lettermark/Lettermark'
import { organizationLogic } from '../../scenes/organizationLogic'
import { router } from 'kea-router'
import { teamLogic } from '../../scenes/teamLogic'
import './Breadcrumbs.scss'

import { breadcrumbsLogicType } from './BreadcrumbsType'
import { IconExpandMore } from '../../lib/components/icons'
import { Link } from '../../lib/components/Link'

interface Breadcrumb {
    name: string
    path: string
}

const breadcrumbsLogic = kea<breadcrumbsLogicType>({
    props: {} as { hashParams: Record<string, any> },
    connect: () => ({
        values: [
            organizationLogic,
            ['currentOrganization'],
            teamLogic,
            ['currentTeam'],
            router,
            ['hashParams', 'location'],
        ],
    }),
    selectors: () => ({
        breadcrumbs: [
            (s) => [s.currentOrganization, s.currentTeam, s.hashParams, s.location],
            (currentOrganization, currentTeam, hashParams) => {
                const breadcrumbs: Breadcrumb[] = []
                if (currentOrganization) {
                    breadcrumbs.push({
                        name: currentOrganization.name,
                        path: `/organization/settings`,
                    })
                }
                if (currentTeam) {
                    breadcrumbs.push({
                        name: currentTeam.name,
                        path: `/project/settings`,
                    })
                }
                if (hashParams.fromItem) {
                    breadcrumbs.push({
                        name: 'Insights',
                        path: `/saved_insights`,
                    })
                }
                return breadcrumbs
            },
        ],
    }),
})

function Breadcrumb({ breadcrumb, withLettermark }: { breadcrumb: Breadcrumb; withLettermark?: boolean }): JSX.Element {
    return (
        <Link to={breadcrumb.path}>
            <div className="Breadcrumbs__breadcrumb">
                {withLettermark && <Lettermark name={breadcrumb.name} />}
                {breadcrumb.name}
            </div>
        </Link>
    )
}

export function Breadcrumbs(): JSX.Element | false {
    const { breadcrumbs } = useValues(breadcrumbsLogic)

    return (
        breadcrumbs.length > 0 && (
            <div className="Breadcrumbs">
                <Breadcrumb breadcrumb={breadcrumbs[0]} withLettermark />
                {breadcrumbs.slice(1).map((breadcrumb) => (
                    <React.Fragment key={breadcrumb.name}>
                        <IconExpandMore className="Breadcrumbs__separator" />
                        <Breadcrumb breadcrumb={breadcrumb} />
                    </React.Fragment>
                ))}
            </div>
        )
    )
}
