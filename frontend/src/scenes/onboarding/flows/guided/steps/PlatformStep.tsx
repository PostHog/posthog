import { useActions, useValues } from 'kea'

import { IconLaptop, IconPhone, IconServer } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { SDKKey } from '~/types'

import { ChoiceList } from '../components/ChoiceList'
import { StackLogos } from '../components/StackLogos'
import { StepLayout } from '../components/StepLayout'
import type { Platform } from '../focusOptions'
import { guidedOnboardingLogic } from '../guidedOnboardingLogic'

export function PlatformStep(): JSX.Element {
    const { platforms, displayName } = useValues(guidedOnboardingLogic)
    const { togglePlatform, next } = useActions(guidedOnboardingLogic)

    return (
        <StepLayout
            title={`Where does ${displayName} run?`}
            description="Pick all that apply."
            primary={
                <Button
                    variant="primary"
                    onClick={next}
                    disabledReason={platforms.length === 0 ? 'Pick at least one' : undefined}
                    data-attr="guided-onboarding-platform-continue"
                >
                    Continue
                </Button>
            }
        >
            <ChoiceList<Platform>
                choices={[
                    {
                        value: 'web',
                        title: 'Web app',
                        description: (
                            <StackLogos
                                sdkKeys={[
                                    SDKKey.NEXT_JS,
                                    SDKKey.REACT,
                                    SDKKey.VUE_JS,
                                    SDKKey.ANGULAR,
                                    SDKKey.SVELTE,
                                    SDKKey.NUXT_JS,
                                    SDKKey.ASTRO,
                                    SDKKey.REMIX,
                                    SDKKey.JS_WEB,
                                ]}
                            />
                        ),
                        icon: <IconLaptop />,
                    },
                    {
                        value: 'mobile',
                        title: 'Mobile app',
                        description: (
                            <StackLogos
                                sdkKeys={[SDKKey.IOS, SDKKey.ANDROID, SDKKey.REACT_NATIVE, SDKKey.FLUTTER, SDKKey.KMP]}
                            />
                        ),
                        icon: <IconPhone />,
                    },
                    {
                        value: 'server',
                        title: 'Backend service',
                        description: (
                            <StackLogos
                                sdkKeys={[
                                    SDKKey.NODE_JS,
                                    SDKKey.PYTHON,
                                    SDKKey.DJANGO,
                                    SDKKey.RUBY_ON_RAILS,
                                    SDKKey.LARAVEL,
                                    SDKKey.GO,
                                    SDKKey.JAVA,
                                    SDKKey.DOTNET,
                                    SDKKey.RUST,
                                    SDKKey.ELIXIR,
                                ]}
                            />
                        ),
                        icon: <IconServer />,
                    },
                ]}
                selected={platforms}
                onSelect={togglePlatform}
                dataAttrPrefix="guided-onboarding-platform"
            />
        </StepLayout>
    )
}
