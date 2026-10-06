import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonSegmentedButton } from '@posthog/lemon-ui'

import { TransformationsFlowMode, transformationsFlowLogic } from './transformationsFlowLogic'
import { TransformationsFlowOverview } from './TransformationsFlowOverview'
import { TransformationsFlowStepDetails } from './TransformationsFlowStepDetails'
import { TransformationsFlowTestPanel } from './TransformationsFlowTestPanel'
import { getStepText } from './transformationsFlowUtils'

export function TransformationsFlowPanel(): JSX.Element {
    const { mode, selectedStep } = useValues(transformationsFlowLogic)
    const { setMode, selectStep } = useActions(transformationsFlowLogic)

    return (
        <div className="flex flex-col gap-3 p-3 border rounded bg-surface-primary min-w-0">
            <LemonSegmentedButton
                size="small"
                fullWidth
                value={mode}
                onChange={(value) => setMode(value as TransformationsFlowMode)}
                options={[
                    { value: 'build', label: 'Steps', 'data-attr': 'transformations-flow-mode-build' },
                    { value: 'test', label: 'Test an event', 'data-attr': 'transformations-flow-mode-test' },
                ]}
            />
            {mode === 'test' ? (
                <TransformationsFlowTestPanel />
            ) : selectedStep ? (
                <>
                    <div className="flex items-center gap-2 min-w-0">
                        <h3 className="flex-1 min-w-0 m-0 truncate">{getStepText(selectedStep).title}</h3>
                        <LemonButton size="small" icon={<IconX />} onClick={() => selectStep(null)} tooltip="Close" />
                    </div>
                    <LemonDivider className="my-0" />
                    <TransformationsFlowStepDetails step={selectedStep} />
                </>
            ) : (
                <TransformationsFlowOverview />
            )}
        </div>
    )
}
