import { PreviewTag } from 'lib/lemon-ui/PreviewTag'
import { SelectableCard } from 'scenes/experiments/components/SelectableCard'

import type { Experiment } from '~/types'

type ExperimentTypePanelProps = {
    experiment: Experiment
    setExperimentType: (type: 'product' | 'web') => void
}

export const ExperimentTypePanel = ({ experiment, setExperimentType }: ExperimentTypePanelProps): JSX.Element => (
    <div className="flex gap-4">
        <SelectableCard
            title="Product experiment"
            description="Use custom code to manage how variants modify your product."
            selected={experiment.type === 'product'}
            onClick={() => setExperimentType('product')}
        />
        <SelectableCard
            title={
                <span>
                    No-Code experiment&nbsp;
                    <PreviewTag stage="beta" size="small" />
                </span>
            }
            description="Define variants on your website using the PostHog toolbar, no coding required."
            selected={experiment.type === 'web'}
            onClick={() => setExperimentType('web')}
        />
    </div>
)
