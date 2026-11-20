import { useValues } from 'kea'

import { Button, Card, CardContent, CardHeader, CardTitle, Text } from '@posthog/quill'

import { warehouseConsoleOverviewLogic } from './warehouseConsoleOverviewLogic'
import { WarehouseHomeLink } from './WarehouseHomeLink'

// pinned: the data-attr values in this file feed autocapture and dashboards, so renaming them breaks both.

export function WarehouseRecommendations(): JSX.Element | null {
    const { recommendations } = useValues(warehouseConsoleOverviewLogic)
    if (recommendations.length === 0) {
        return null
    }
    return (
        <Card data-attr="warehouse-home-recommendations">
            <CardHeader>
                <CardTitle>Recommendations</CardTitle>
            </CardHeader>
            <CardContent>
                <ul className="m-0 flex list-none flex-col gap-3 p-0">
                    {recommendations.map((item) => (
                        <li key={item.key} className="flex flex-wrap items-center justify-between gap-2">
                            <div className="min-w-0">
                                <Text size="sm" weight="medium">
                                    {item.title}
                                </Text>
                                <Text size="xs" variant="muted">
                                    {item.description}
                                </Text>
                            </div>
                            <Button
                                size="sm"
                                nativeButton={false}
                                render={
                                    <WarehouseHomeLink
                                        to={item.to}
                                        section={`recommendation_${item.key}`}
                                        data-attr={`warehouse-home-recommendation-${item.key}`}
                                    >
                                        {item.actionLabel}
                                    </WarehouseHomeLink>
                                }
                            />
                        </li>
                    ))}
                </ul>
            </CardContent>
        </Card>
    )
}
