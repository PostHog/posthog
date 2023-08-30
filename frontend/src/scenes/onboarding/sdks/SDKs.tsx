import { LemonInput, LemonSelect } from '@posthog/lemon-ui'
import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { SceneExport } from 'scenes/sceneTypes'
import { sdksLogic } from './sdksLogic'
import { LemonCard } from 'lib/lemon-ui/LemonCard/LemonCard'
import { useActions, useValues } from 'kea'

export const scene: SceneExport = {
    component: SDKs,
    // logic: onboardingLogic,
}

export function SDKs(): JSX.Element {
    const { setSourceFilter } = useActions(sdksLogic)
    const { sourceFilter, sdks } = useValues(sdksLogic)
    return (
        <BridgePage view="onboarding-sdks" noLogo hedgehog={false} fixedWidth={false}>
            <div className="max-w-md">
                <h1>Where are you collecting events from?</h1>
                <p>Pick one to start and add more sources later.</p>
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
                        <LemonCard
                            className="w-32 flex flex-col items-center text-center"
                            key={'sdk-option-' + sdk.key}
                        >
                            <div className="h-8 mb-4">
                                <img src={sdk.image} className="w-8" />
                            </div>
                            <h4 className="mb-0 leading-4">{sdk.name}</h4>
                        </LemonCard>
                    ))}
                </div>
            </div>
        </BridgePage>
    )
}
