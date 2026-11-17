import { IconGraph } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { ExperimentMetric } from '~/queries/schema/schema-general'

export function DetailsButton({
    setIsModalOpen,
}: {
    metric: ExperimentMetric
    setIsModalOpen: (isOpen: boolean) => void
}): JSX.Element {
    return (
        <>
            <LemonButton type="secondary" size="xsmall" icon={<IconGraph />} onClick={() => setIsModalOpen(true)}>
                Details
            </LemonButton>
        </>
    )
}
