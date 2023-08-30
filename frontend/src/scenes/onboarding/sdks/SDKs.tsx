import { LemonInput, LemonTag } from '@posthog/lemon-ui'
import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { SceneExport } from 'scenes/sceneTypes'
import { allSDKs } from './sdksLogic'
import { LemonCard } from 'lib/lemon-ui/LemonCard/LemonCard'

export const scene: SceneExport = {
    component: SDKs,
    // logic: onboardingLogic,
}

enum SDKTagType {
    web = 'success',
    mobile = 'highlight',
    server = 'completion',
}

export function SDKs(): JSX.Element {
    return (
        <BridgePage view="onboarding-sdks" noLogo hedgehog={false} fixedWidth={false}>
            <div className="max-w-md">
                <h1>Where are you collecting events from?</h1>
                <p>Pick one to start and add more sources later.</p>
                <LemonInput placeholder="Search for a source" type="search" />
                <div className="flex flex-wrap gap-x-4 gap-y-4 mt-8 justify-center">
                    {allSDKs.map((sdk) => (
                        <LemonCard
                            className="w-32 flex flex-col items-center text-center"
                            key={'sdk-option-' + sdk.key}
                        >
                            <div className="h-8 mb-4">
                                <img src={sdk.image} className="w-8" />
                            </div>
                            <h4 className="mb-0 leading-4">{sdk.name}</h4>
                            {sdk.tags &&
                                sdk.tags.map((tag) => (
                                    <LemonTag className="mt-2" type={SDKTagType[tag]} key={'sdk-type-' + tag}>
                                        {tag}
                                    </LemonTag>
                                ))}
                        </LemonCard>
                    ))}
                </div>
            </div>
        </BridgePage>
    )
}
