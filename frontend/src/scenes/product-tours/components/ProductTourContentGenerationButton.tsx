import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { ProductTourContentGenerationModal } from './ProductTourContentGenerationModal'
import { productTourContentGenerationLogic } from './productTourContentGenerationLogic'

export interface ProductTourContentGenerationButtonProps {
    tourId: string
}

export function ProductTourContentGenerationButton({ tourId }: ProductTourContentGenerationButtonProps): JSX.Element {
    const { hasPendingSuggestions, pendingSuggestions } = useValues(productTourContentGenerationLogic({ tourId }))
    const { openModal } = useActions(productTourContentGenerationLogic({ tourId }))

    return (
        <>
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconSparkles />}
                onClick={openModal}
                disabledReason={tourId === 'new' ? 'Save the tour first' : undefined}
                fullWidth
            >
                Generate content
                {hasPendingSuggestions && <span className="ml-1 text-muted">({pendingSuggestions.length})</span>}
            </LemonButton>
            <ProductTourContentGenerationModal tourId={tourId} />
        </>
    )
}
