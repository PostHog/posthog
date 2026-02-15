import { useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { ProductTour, ProgressStatus } from '~/types'

import { productTourLogic } from '../productTourLogic'
import { getProductTourStatus, productToursLogic } from '../productToursLogic'

function TourStatusDot({ tour }: { tour: ProductTour }): JSX.Element {
    const status = getProductTourStatus(tour)
    const colorClass =
        status === ProgressStatus.Running ? 'bg-success' : status === ProgressStatus.Draft ? 'bg-muted-alt' : 'bg-muted'

    return <span className={`inline-block w-2 h-2 rounded-full ${colorClass}`} />
}

export interface TourSelectorProps {
    value: string | undefined
    onChange: (tourId: string) => void
    size?: 'small' | 'medium'
    fullWidth?: boolean
    className?: string
}

export function TourSelector({
    value,
    onChange,
    size = 'small',
    fullWidth,
    className,
}: TourSelectorProps): JSX.Element {
    const { productTours } = useValues(productToursLogic)
    const { productTour } = useValues(productTourLogic)

    const options = productTours
        .filter((tour) => !tour.archived && tour.id !== productTour?.id)
        .map((tour) => ({
            value: tour.id,
            label: (
                <span className="flex items-center gap-2">
                    <TourStatusDot tour={tour} />
                    {tour.name}
                </span>
            ),
        }))

    return (
        <LemonSelect
            value={value}
            onChange={onChange}
            options={options}
            placeholder="Select a tour..."
            size={size}
            fullWidth={fullWidth}
            className={className}
        />
    )
}
