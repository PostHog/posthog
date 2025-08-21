import type { Meta } from '@storybook/react'

import { LemonButton } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

const meta = {
    title: 'Scenes/SceneSection',
    tags: ['autodocs'],
    component: SceneSection,
    parameters: {
        featureFlags: [FEATURE_FLAGS.NEW_SCENE_LAYOUT],
    },
} satisfies Meta<typeof SceneSection>

export default meta

function Wrapper({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="max-w-2xl">{children}</div>
}

// Default because we encourage title and descriptions
export function SceneSectionDefault(): JSX.Element {
    return (
        <Wrapper>
            <SceneSection title="Don't be a fool, wrap your sections" description="Section description">
                <div>item 1</div>
                <div>item 2</div>
                <div>item 3</div>
            </SceneSection>
        </Wrapper>
    )
}
export function SceneSectionJustTitle(): JSX.Element {
    return (
        <Wrapper>
            <SceneSection title="Don't be a fool, wrap your sections">
                <div>item 1</div>
                <div>item 2</div>
                <div>item 3</div>
            </SceneSection>
        </Wrapper>
    )
}
export function SceneSectionNoTitleAndDescription(): JSX.Element {
    return (
        <Wrapper>
            <SceneSection>
                <div>item 1</div>
                <div>item 2</div>
                <div>item 3</div>
            </SceneSection>
        </Wrapper>
    )
}
export function SceneSectionWithTitleAndActions(): JSX.Element {
    return (
        <Wrapper>
            <SceneSection
                title="Don't be a fool, wrap your sections, extra long to show how it wraps"
                actions={
                    <>
                        <LemonButton type="primary" size="small">
                            An Action
                        </LemonButton>
                        <LemonButton type="primary" size="small">
                            An Action
                        </LemonButton>
                    </>
                }
            >
                <div>item 1</div>
                <div>item 2</div>
                <div>item 3</div>
            </SceneSection>
        </Wrapper>
    )
}
export function SceneSectionWithTitleAndDescriptionAndActions(): JSX.Element {
    return (
        <Wrapper>
            <SceneSection
                title="Don't be a fool, wrap your sections, extra long to show how it wraps"
                description="Section longer description to show how it wraps, and how it wraps around the actions"
                actions={
                    <>
                        <LemonButton type="primary" size="small">
                            An Action
                        </LemonButton>
                        <LemonButton type="primary" size="small">
                            An Action
                        </LemonButton>
                    </>
                }
            >
                <div>item 1</div>
                <div>item 2</div>
                <div>item 3</div>
            </SceneSection>
        </Wrapper>
    )
}
