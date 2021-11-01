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
        values: [organizationLogic, ['currentOrganization'], teamLogic, ['currentTeam']],
    }),
    selectors: ({ props }) => ({
        breadcrumbs: [
            (s) => [s.currentOrganization, s.currentTeam, () => props.hashParams],
            (currentOrganization, currentTeam, hashParams) => {
                if (!currentOrganization || !currentTeam) {
                    return []
                }
                const breadcrumbs: Breadcrumb[] = [
                    {
                        name: currentOrganization.name,
                        path: `/organization/settings`,
                    },
                    {
                        name: currentTeam.name,
                        path: `/project/settings`,
                    },
                ]
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

export function Breadcrumbs(): JSX.Element {
    const { hashParams } = useValues(router)
    const { breadcrumbs } = useValues(breadcrumbsLogic({ hashParams }))

    return (
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
}
