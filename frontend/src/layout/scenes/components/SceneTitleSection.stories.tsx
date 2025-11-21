import type { Meta } from '@storybook/react'

import { IconPlus } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { SceneContent } from './SceneContent'
import { SceneTitleSection } from './SceneTitleSection'

const meta = {
    title: 'Scenes/SceneTitleSection',
    component: SceneTitleSection as any,
    tags: ['autodocs'],
    parameters: {
        layout: 'fullscreen',
    },
} satisfies Meta<typeof SceneTitleSection>

export default meta

const LONG_NAME = 'Long name here that will truncate if too long'

function Wrapper({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <main id="main-content" className="@container/main-content bg-surface-tertiary">
            <div className="max-w-[350px] h-[500px] relative p-4 bg-primary min-h-screen [&_.scene-title-section-wrapper]:top-0 [&_.scene-title-section-wrapper-sticky-sentinel]:top-[-7px]">
                <SceneContent>
                    {children}

                    <p>Some content below the title section</p>
                    <p>Some content below the title section</p>
                    <p>Some content below the title section</p>
                    <p>Some content below the title section</p>
                    <p>Some content below the title section</p>
                    <p>Some content below the title section</p>
                    <p>Some content below the title section</p>
                    <p>Some content below the title section</p>
                    <p>Some content below the title section</p>
                </SceneContent>
            </div>
        </main>
    )
}
export function Default(): JSX.Element {
    return (
        <Wrapper>
            <SceneTitleSection
                name={LONG_NAME}
                description="Non editable description"
                resourceType={{
                    type: 'cohort',
                }}
                canEdit={false}
            />
        </Wrapper>
    )
}

export function Editable(): JSX.Element {
    return (
        <Wrapper>
            <SceneTitleSection
                name={LONG_NAME}
                description="Editable description"
                resourceType={{
                    type: 'cohort',
                }}
                canEdit={true}
                onNameChange={(value) => {}}
                onDescriptionChange={(value) => {}}
            />
        </Wrapper>
    )
}

export function ForceEdit(): JSX.Element {
    return (
        <Wrapper>
            <SceneTitleSection
                name={LONG_NAME}
                description="Editable description"
                resourceType={{
                    type: 'cohort',
                }}
                forceEdit={true}
                canEdit={true}
                onNameChange={(value) => {}}
                onDescriptionChange={(value) => {}}
            />
        </Wrapper>
    )
}

export function EditableNoDescription(): JSX.Element {
    return (
        <Wrapper>
            <SceneTitleSection
                name="Editable name but very long name that shows truncation, and does not wrap!"
                description={null}
                resourceType={{ type: 'cohort' }}
                canEdit={true}
            />
        </Wrapper>
    )
}

export function Actions(): JSX.Element {
    return (
        <Wrapper>
            <SceneTitleSection
                name="Editable name but very long name that shows truncation, and does not wrap!"
                description={null}
                resourceType={{ type: 'cohort' }}
                canEdit={true}
                actions={
                    <LemonButton icon={<IconPlus />} size="small" type="secondary">
                        Add action
                    </LemonButton>
                }
            />
        </Wrapper>
    )
}

export function ForceBackTo(): JSX.Element {
    return (
        <Wrapper>
            <SceneTitleSection
                name="Editable name but very long name that shows truncation, and does not wrap!"
                description={null}
                resourceType={{ type: 'cohort' }}
                canEdit={true}
                forceBackTo={{
                    name: 'Cohorts',
                    path: '/cohorts',
                    type: 'cohort',
                    key: 'cohorts',
                }}
            />
        </Wrapper>
    )
}
