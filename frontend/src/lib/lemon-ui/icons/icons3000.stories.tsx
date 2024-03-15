import * as packageIcons from '@posthog/icons'
import { Meta, StoryObj } from '@storybook/react'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'

import { LemonCollapse } from '../LemonCollapse'
import { ELEMENTS, OBJECTS, TEAMS_AND_COMPANIES, TECHNOLOGY } from './categories'

const meta: Meta = {
    title: 'PostHog 3000/Icons',
    tags: ['test-skip'],
    parameters: {
        previewTabs: {
            'storybook/docs/panel': {
                hidden: true,
            },
        },
    },
}
export default meta

const posthogIcons = Object.entries(packageIcons)
    .filter(([key]) => key !== 'BaseIcon')
    .map(([key, Icon]) => ({ name: key, icon: Icon }))

const IconTemplate = ({ icons }: { icons: { name: string; icon: any }[] }): JSX.Element => {
    return (
        <div className="grid grid-cols-6 gap-4">
            {icons.map(({ name, icon: Icon }) => {
                return (
                    <div key={name} className="flex flex-col items-center space-y-2">
                        <Icon className="w-10 h-10" />
                        <CopyToClipboardInline className="text-xs">{name}</CopyToClipboardInline>
                    </div>
                )
            })}
        </div>
    )
}

export function Alphabetical(): JSX.Element {
    return <IconTemplate icons={posthogIcons} />
}

const GroupBase = ({ group }: { group: Record<string, string[]> }): JSX.Element => {
    return (
        <LemonCollapse
            multiple
            panels={Object.entries(group).map(([key, icons]) => {
                return {
                    key,
                    header: key,
                    content: (
                        <IconTemplate
                            icons={icons.map((icon) => {
                                return { name: icon, icon: packageIcons[icon] }
                            })}
                        />
                    ),
                }
            })}
        />
    )
}

export const Elements: StoryObj = (): JSX.Element => {
    return <GroupBase group={ELEMENTS} />
}
Elements.storyName = 'Category - Elements'

export const TeamsAndCompanies: StoryObj = (): JSX.Element => {
    return <GroupBase group={TEAMS_AND_COMPANIES} />
}
TeamsAndCompanies.storyName = 'Category - Teams & Companies'

export const Technology: StoryObj = (): JSX.Element => {
    return <GroupBase group={TECHNOLOGY} />
}
Technology.storyName = 'Category - Technology'

export const Objects: StoryObj = (): JSX.Element => {
    return <GroupBase group={OBJECTS} />
}
Objects.storyName = 'Category - Objects'
