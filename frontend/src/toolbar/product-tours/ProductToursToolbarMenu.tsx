import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { Spinner } from 'lib/lemon-ui/Spinner'

import { ToolbarMenu } from '~/toolbar/bar/ToolbarMenu'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'

import { productToursLogic } from './productToursLogic'

export function ProductToursToolbarMenu(): JSX.Element {
    const { selectTour } = useActions(productToursLogic)
    const { tours, toursLoading } = useValues(productToursLogic)
    const { uiHost } = useValues(toolbarConfigLogic)

    const filteredTours = tours.filter((tour) => !tour.archived && tour.content?.type !== 'announcement')

    return (
        <ToolbarMenu>
            <ToolbarMenu.Header>
                <span>Product tours</span>
            </ToolbarMenu.Header>
            <ToolbarMenu.Body>
                <div className="p-2 space-y-3">
                    {toursLoading ? (
                        <div className="flex justify-center py-4">
                            <Spinner />
                        </div>
                    ) : filteredTours.length > 0 ? (
                        <div className="space-y-1">
                            <div className="text-xs font-medium text-muted uppercase">Select a tour to view</div>
                            {filteredTours.map((tour) => (
                                <LemonButton
                                    key={tour.id}
                                    fullWidth
                                    type="secondary"
                                    size="small"
                                    onClick={() => selectTour(tour.id)}
                                >
                                    <span className="truncate">{tour.name}</span>
                                    <span className="text-muted text-xs ml-auto">
                                        {tour.content?.steps?.length ?? 0} steps
                                    </span>
                                </LemonButton>
                            ))}
                        </div>
                    ) : (
                        <p className="text-muted text-sm text-center py-2">No tours yet</p>
                    )}

                    <div className="pt-2 border-t">
                        <LemonButton
                            type="tertiary"
                            size="small"
                            fullWidth
                            onClick={() => window.open(`${uiHost}/product_tours/new`, '_blank')}
                        >
                            Create tour in PostHog →
                        </LemonButton>
                    </div>
                </div>
            </ToolbarMenu.Body>
        </ToolbarMenu>
    )
}
