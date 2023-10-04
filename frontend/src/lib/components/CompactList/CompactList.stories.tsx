import { Meta } from '@storybook/react'

import { CompactList } from './CompactList'
import { urls } from 'scenes/urls'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'

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
            {/* eslint-disable-next-line react/forbid-dom-props */}
            <div style={{ width: 350 }}>
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
                        <LemonButton key={index} fullWidth onClick={() => {}}>
                            <PersonDisplay withIcon person={person} />
                        </LemonButton>
                    )}
                />
            </div>
            {/* eslint-disable-next-line react/forbid-dom-props */}
            <div style={{ width: 350, marginLeft: 30 }}>
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
                        <LemonButton key={index} fullWidth onClick={() => {}}>
                            <PersonDisplay withIcon person={person} />
                        </LemonButton>
                    )}
                />
            </div>
        </div>
    )
}
