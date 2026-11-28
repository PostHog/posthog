import { useContext } from 'react'

import { Button, Progress } from '@posthog/quill'

import { PropertyOperator } from '~/types'

import type { PropertyFilterValue } from '../../filters/property/propertyFilterSpec'
import { FilterControlsContext } from '../../filters/filtersContext'

const BROWSER_FILTER_ID = 'browser'
const BROWSERS = [
    { name: 'Chrome', share: 64 },
    { name: 'Safari', share: 19 },
    { name: 'Firefox', share: 9 },
    { name: 'Edge', share: 8 },
]

function pickedBrowser(value: unknown): string | null {
    const [condition] = (value as PropertyFilterValue | undefined) ?? []
    return condition?.operator === PropertyOperator.Exact && Array.isArray(condition.value)
        ? (condition.value[0] ?? null)
        : null
}

// TODO(2026-11-26): Delete with the kitchen sink fixture, once a product drives its filters from its own custom content.
export function BrowserFilterList(): JSX.Element {
    const { filters } = useContext(FilterControlsContext)
    const picked = pickedBrowser(filters?.values[BROWSER_FILTER_ID])
    return (
        <div className="flex flex-col gap-1">
            {BROWSERS.map(({ name, share }) => (
                <Button
                    key={name}
                    variant={picked === name ? 'outline' : 'default'}
                    size="sm"
                    className="justify-between"
                    aria-pressed={picked === name}
                    disabledReason={filters ? undefined : 'This dashboard has no filters'}
                    data-attr="dashboard-v2-example-browser-filter"
                    onClick={() =>
                        filters?.onValueChange(
                            BROWSER_FILTER_ID,
                            picked === name ? undefined : [{ operator: PropertyOperator.Exact, value: [name] }]
                        )
                    }
                >
                    <span className="w-20 text-left">{name}</span>
                    <Progress value={share} className="flex-1" />
                    <span className="w-10 text-right tabular-nums">{share}%</span>
                </Button>
            ))}
        </div>
    )
}
