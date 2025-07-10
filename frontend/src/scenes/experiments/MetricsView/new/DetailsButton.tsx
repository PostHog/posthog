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
            <div
                className="absolute top-2 left-2 flex justify-center bg-[var(--bg-table)] z-[101]"
                // Chart is z-index 100, so we need to be above it
            >
                <LemonButton type="secondary" size="xsmall" icon={<IconGraph />} onClick={() => setIsModalOpen(true)}>
                    Details
                </LemonButton>
            </div>
        </>
    )
}
