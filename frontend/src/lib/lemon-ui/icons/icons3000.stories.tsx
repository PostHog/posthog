import { Meta, StoryObj } from '@storybook/react'

import * as packageIcons from '@posthog/icons'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { LemonCollapse } from '../LemonCollapse'
import { Tooltip } from '../Tooltip'
import { ELEMENTS, OBJECTS, TEAMS_AND_COMPANIES, TECHNOLOGY } from './categories'

export type IconCollection = readonly Exclude<keyof typeof packageIcons, 'BaseIcon'>[]

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
    const onClick = (name: string): void => {
        void copyToClipboard(name)
    }

    return (
        <div className="grid grid-cols-6 gap-4">
            {icons.map(({ name, icon: Icon }) => {
                return (
                    <div onClick={() => onClick(name)} key={name} className="flex justify-center">
                        <Tooltip title="Click to copy">
                            <div className="flex flex-col items-center deprecated-space-y-2 max-w-24 py-2 px-4 cursor-pointer rounded hover:bg-secondary-3000">
                                <Icon className="w-10 h-10" />
                                <span className="text-xs">{name}</span>
                            </div>
                        </Tooltip>
                    </div>
                )
            })}
        </div>
    )
}

export const Alphabetical: StoryObj = {
    render: () => <IconTemplate icons={posthogIcons} />,
}

const GroupBase = ({ group }: { group: Record<string, IconCollection> }): JSX.Element => {
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

export const Elements: StoryObj = {
    render: () => <GroupBase group={ELEMENTS} />,
    storyName: 'Category - Elements',
}

export const TeamsAndCompanies: StoryObj = {
    render: () => <GroupBase group={TEAMS_AND_COMPANIES} />,
    storyName: 'Category - Teams & Companies',
}

export const Technology: StoryObj = {
    render: () => <GroupBase group={TECHNOLOGY} />,
    storyName: 'Category - Technology',
}

export const Objects: StoryObj = {
    render: () => <GroupBase group={OBJECTS} />,
    storyName: 'Category - Objects',
}
