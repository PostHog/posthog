import type { Meta } from '@storybook/react'

import { IconInfo } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'

import { SceneSection, SceneTitleSection } from './SceneContent'

const meta = {
    title: 'Scenes/SceneContent',
    tags: ['autodocs'],
    parameters: {
        featureFlags: [FEATURE_FLAGS.NEW_SCENE_LAYOUT],
    },
} satisfies Meta

export default meta

function Wrapper({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="max-w-2xl">{children}</div>
}

export function SceneTitleSectionDefault(): JSX.Element {
    return (
        <Wrapper>
            <SceneTitleSection
                name="Scene title"
                description="Scene description"
                resourceType={{
                    type: 'action',
                    typePlural: 'actions',
                }}
            />
        </Wrapper>
    )
}
export function SceneTitleSectionCustomIconAndColor(): JSX.Element {
    return (
        <Wrapper>
            <SceneTitleSection
                name="Scene title"
                description="Scene description"
                resourceType={{
                    type: 'action',
                    typePlural: 'actions',
                    forceIcon: <IconInfo />,
                    forceIconColorOverride: ['var(--brand-red)', 'var(--brand-blue)'],
                }}
            />
        </Wrapper>
    )
}

export function SceneTitleSectionJustName(): JSX.Element {
    return (
        <Wrapper>
            <SceneTitleSection
                name="Scene title"
                description={null}
                resourceType={{
                    type: 'action',
                    typePlural: 'actions',
                }}
            />
        </Wrapper>
    )
}

export function SceneTitleSectionWithDocsURL(): JSX.Element {
    return (
        <Wrapper>
            <SceneTitleSection
                name="Scene title"
                description="Scene description"
                resourceType={{
                    type: 'action',
                    typePlural: 'actions',
                }}
                docsURL="https://posthog.com/docs/action"
            />
        </Wrapper>
    )
}

export function SceneTitleSectionWithEditableFields(): JSX.Element {
    return (
        <Wrapper>
            <SceneTitleSection
                name="Scene title"
                description={`# Scene description

* List item 1
* List item 2
* List item 3`}
                resourceType={{
                    type: 'action',
                    typePlural: 'actions',
                }}
                docsURL="https://posthog.com/docs/action"
                onDescriptionBlur={(description) => {
                    console.info(description)
                }}
                onNameBlur={(name) => {
                    console.info(name)
                }}
                canEdit
            />
        </Wrapper>
    )
}

export function SceneTitleSectionWithEditableFieldsNoDescription(): JSX.Element {
    return (
        <Wrapper>
            <SceneTitleSection
                name="Scene title"
                description={null}
                resourceType={{
                    type: 'action',
                    typePlural: 'actions',
                }}
                docsURL="https://posthog.com/docs/action"
                onNameBlur={(name) => {
                    console.info(name)
                }}
                canEdit
            />
        </Wrapper>
    )
}
export function SceneTitleSectionWithMarkdown(): JSX.Element {
    return (
        <Wrapper>
            <SceneTitleSection
                name="Scene title"
                description={`# Scene description

* List item 1
* List item 2
* List item 3`}
                resourceType={{
                    type: 'action',
                    typePlural: 'actions',
                }}
                markdown
            />
        </Wrapper>
    )
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
