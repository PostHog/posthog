import React from 'react'
import { ComponentMeta } from '@storybook/react'

import { CompactList } from './CompactList'
import { urls } from 'scenes/urls'
import { LemonButton } from '../LemonButton'
import { PersonHeader } from 'scenes/persons/PersonHeader'

export default {
    title: 'Components/Compact List',
    component: CompactList,
    argTypes: {
        loading: {
            control: {
                type: 'boolean',
            },
        },
    },
} as ComponentMeta<typeof CompactList>

export function CompactList_({ loading }: { loading: boolean }): JSX.Element {
    return (
        <div style={{ display: 'flex' }}>
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
                            <PersonHeader withIcon person={person} />
                        </LemonButton>
                    )}
                />
            </div>
            <div style={{ width: 350, marginLeft: 30 }}>
                <CompactList
                    loading={loading}
                    title="Recordings"
                    viewAllURL={urls.sessionRecordings()}
                    emptyMessage={{
                        title: 'There are no recordings for this project',
                        description: 'Make sure you have the javascript snippet setup in your website.',
                        buttonText: 'Learn more',
                        buttonHref: 'https://posthog.com/docs/user-guides/recordings',
                    }}
                    items={[]}
                    renderRow={(person, index) => (
                        <LemonButton key={index} fullWidth onClick={() => {}}>
                            <PersonHeader withIcon person={person} />
                        </LemonButton>
                    )}
                />
            </div>
        </div>
    )
}
