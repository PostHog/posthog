import { LemonInput, LemonSelect } from '@posthog/lemon-ui'
import { sdksLogic } from './sdksLogic'
import { LemonCard } from 'lib/lemon-ui/LemonCard/LemonCard'
import { useActions, useValues } from 'kea'
import { OnboardingStep } from '../OnboardingStep'

export function SDKs({ usersAction }: { usersAction?: string }): JSX.Element {
    const { setSourceFilter } = useActions(sdksLogic)
    const { sourceFilter, sdks } = useValues(sdksLogic)
    return (
        <OnboardingStep
            title={`Where are you ${usersAction || 'collecting data'} from?`}
            subtitle="Pick one to start and add more sources later."
        >
            <div className="flex gap-x-4">
                <LemonInput placeholder="Search for a source" type="search" />
                <LemonSelect
                    allowClear
                    onChange={(v) => setSourceFilter(v)}
                    options={[
                        {
                            label: 'Web',
                            value: 'web',
                        },
                        {
                            label: 'Mobile',
                            value: 'mobile',
                        },
                        {
                            label: 'Server',
                            value: 'server',
                        },
                    ]}
                    placeholder="Select a source type"
                    value={sourceFilter}
                />
            </div>
            <div className="flex flex-wrap gap-x-4 gap-y-4 mt-8 justify-center">
                {sdks.map((sdk) => (
                    <LemonCard className="w-32 flex flex-col items-center text-center" key={'sdk-option-' + sdk.key}>
                        <div className="h-8 mb-4">
                            <img src={sdk.image} className="w-8" />
                        </div>
                        <h4 className="mb-0 leading-4">{sdk.name}</h4>
                    </LemonCard>
                ))}
            </div>
        </OnboardingStep>
    )
}
