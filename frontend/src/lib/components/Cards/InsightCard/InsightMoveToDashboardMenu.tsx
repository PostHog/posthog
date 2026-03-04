import React, { useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonMenu, LemonMenuItem, LemonMenuItems } from 'lib/lemon-ui/LemonMenu'

import type { DashboardBasicType } from '~/types'

interface InsightMoveToDashboardMenuProps {
    otherDashboards: DashboardBasicType[]
    onMoveToDashboard: (dashboard: DashboardBasicType) => void
}

export function InsightMoveToDashboardMenu({
    otherDashboards,
    onMoveToDashboard,
}: InsightMoveToDashboardMenuProps): JSX.Element | null {
    const [searchTerm, setSearchTerm] = useState('')

    if (!otherDashboards.length) {
        return null
    }

    const filteredDashboards =
        searchTerm.trim() === ''
            ? otherDashboards
            : otherDashboards.filter((dashboard) =>
                  (dashboard.name || 'Untitled').toLowerCase().includes(searchTerm.toLowerCase())
              )

    const searchItem: LemonMenuItem = {
        custom: true,
        label: () => (
            <div className="px-2 pt-2 pb-1">
                <LemonInput
                    type="search"
                    placeholder="Search dashboards"
                    value={searchTerm}
                    onChange={setSearchTerm}
                    size="small"
                    fullWidth
                    allowClear
                    onClick={(e) => e.stopPropagation()}
                    autoFocus
                />
            </div>
        ),
    }

    const items: LemonMenuItems =
        filteredDashboards.length > 0
            ? [
                  { items: [searchItem] },
                  {
                      items: filteredDashboards.map((dashboard) => ({
                          label: dashboard.name || <i>Untitled</i>,
                          key: dashboard.id,
                          onClick: () => {
                              onMoveToDashboard(dashboard)
                              setSearchTerm('')
                          },
                      })),
                  },
              ]
            : [
                  {
                      items: [
                          searchItem,
                          {
                              label: 'No dashboards match this search',
                              disabledReason: 'No dashboards match this search',
                              onClick: () => {},
                              key: 'no-results',
                          },
                      ],
                  },
              ]

    return (
        <LemonMenu
            items={items}
            placement="right-start"
            fallbackPlacements={['left-start']}
            closeParentPopoverOnClickInside
        >
            <LemonButton fullWidth>Move to</LemonButton>
        </LemonMenu>
    )
}
