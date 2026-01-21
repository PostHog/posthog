import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { Spinner } from 'lib/lemon-ui/Spinner'

import { ToolbarMenu } from '~/toolbar/bar/ToolbarMenu'

import { productToursLogic } from './productToursLogic'

export function ProductToursToolbarMenu(): JSX.Element {
    const { startCreation, selectTour } = useActions(productToursLogic)
    const { tours, toursLoading } = useValues(productToursLogic)

    return (
        <ToolbarMenu>
            <ToolbarMenu.Header>
                <span>Product tours</span>
            </ToolbarMenu.Header>
            <ToolbarMenu.Body>
                <div className="p-2 space-y-3">
                    <LemonButton type="primary" fullWidth onClick={() => startCreation()}>
                        Create new tour
                    </LemonButton>

                    {toursLoading ? (
                        <div className="flex justify-center py-4">
                            <Spinner />
                        </div>
                    ) : tours.length > 0 ? (
                        <div className="space-y-1">
                            <div className="text-xs font-medium text-muted uppercase">Existing tours</div>
                            {tours
                                .filter((tour) => !tour.archived && tour.content?.type !== 'announcement')
                                .map((tour) => (
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
                </div>
            </ToolbarMenu.Body>
        </ToolbarMenu>
    )
}
