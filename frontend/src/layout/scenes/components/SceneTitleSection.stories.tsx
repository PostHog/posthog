import type { Meta } from '@storybook/react'

import { IconInfo } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'

import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

const meta = {
    title: 'Scenes/SceneTitleSection',
    tags: ['autodocs'],
    component: SceneTitleSection,
    parameters: {
        featureFlags: [FEATURE_FLAGS.NEW_SCENE_LAYOUT],
    },
} satisfies Meta<typeof SceneTitleSection>

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
