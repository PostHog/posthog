import { useValues } from 'kea'
import posthog from 'posthog-js'

import { Text } from '@posthog/quill'

import { WarehouseSection } from '../WarehouseConsole/WarehouseSection'
import { WarehouseSectionLink } from '../WarehouseConsole/WarehouseSectionLink'
import { warehouseConsoleOverviewLogic } from './warehouseConsoleOverviewLogic'

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

export function WarehouseRecommendations(): JSX.Element | null {
    const { recommendations } = useValues(warehouseConsoleOverviewLogic)
    if (recommendations.length === 0) {
        return null
    }
    return (
        <WarehouseSection title="Recommendations" data-attr="warehouse-home-recommendations">
            <ul className="m-0 flex list-none flex-col gap-3 p-0">
                {recommendations.map((item) => (
                    <li key={item.key} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                        <div className="min-w-0 flex-1">
                            <Text size="sm" weight="medium">
                                {item.title}
                            </Text>
                            <Text size="xs" variant="muted">
                                {item.description}
                            </Text>
                        </div>
                        <WarehouseSectionLink
                            to={item.to}
                            onClick={() =>
                                posthog.capture('warehouse home link clicked', {
                                    section: `recommendation_${item.key}`,
                                })
                            }
                            data-attr={`warehouse-home-recommendation-${item.key}`}
                        >
                            {item.actionLabel}
                        </WarehouseSectionLink>
                    </li>
                ))}
            </ul>
        </WarehouseSection>
    )
}
