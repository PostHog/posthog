import { useCallback, useState } from 'react'

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
    const [searchTerm, setSearchTermState] = useState('')

    const handleSearchChange = useCallback((value: string) => {
        setSearchTermState(value)
    }, [])

    const filteredDashboards =
        searchTerm.trim() === ''
            ? otherDashboards
            : otherDashboards.filter((dashboard) =>
                  (dashboard.name || 'Untitled').toLowerCase().includes(searchTerm.toLowerCase())
              )

    const SearchInputLabel = useCallback(() => {
        return (
            <div className="px-2 pt-2 pb-1">
                <LemonInput
                    type="search"
                    placeholder="Search dashboards"
                    value={searchTerm}
                    onChange={handleSearchChange}
                    size="small"
                    fullWidth
                    allowClear
                    onClick={(e) => e.stopPropagation()}
                    autoFocus
                />
            </div>
        )
    }, [handleSearchChange, searchTerm])

    const searchItem: LemonMenuItem = {
        custom: true,
        label: SearchInputLabel,
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
                              setSearchTermState('')
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
                              key: 'no-results',
                          },
                      ],
                  },
              ]

    if (!otherDashboards.length) {
        return null
    }

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
