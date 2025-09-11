import { Meta } from '@storybook/react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { urls } from 'scenes/urls'

import { CompactList } from './CompactList'

const meta: Meta<typeof CompactList> = {
    title: 'Components/Compact List',
    component: CompactList,
    argTypes: {
        loading: {
            control: {
                type: 'boolean',
            },
        },
    },
}
export default meta

export function CompactList_({ loading }: { loading: boolean }): JSX.Element {
    return (
        <div className="flex">
            <div className="w-80">
                <CompactList
                    loading={loading}
                    title="Recent persons"
                    viewAllURL={urls.persons()}
                    items={[
                        { properties: { name: 'Person 1' } },
                        { properties: { name: 'Person 2' } },
                        { properties: { name: 'Person 3' } },
                        { properties: { name: 'Person 4' } },
                        { properties: { name: 'Person 5' } },
                        { properties: { name: 'Person 6' } },
                        { properties: { name: 'Person 7' } },
                        { properties: { name: 'Person 8' } },
                    ]}
                    renderRow={(person, index) => (
                        <LemonButton key={index} fullWidth>
                            <PersonDisplay withIcon person={person} />
                        </LemonButton>
                    )}
                />
            </div>
            <div className="w-80 ml-8">
                <CompactList
                    loading={loading}
                    title="Recordings"
                    viewAllURL={urls.replay()}
                    emptyMessage={{
                        title: 'There are no recordings for this project',
                        description: 'Make sure you have the javascript snippet setup in your website.',
                        buttonText: 'Learn more',
                        buttonTo: 'https://posthog.com/docs/user-guides/recordings',
                    }}
                    items={[]}
                    renderRow={(person, index) => (
                        <LemonButton key={index} fullWidth>
                            <PersonDisplay withIcon person={person} />
                        </LemonButton>
                    )}
                />
            </div>
        </div>
    )
}
