import { Meta, StoryFn } from '@storybook/react'
import { BindLogic, useActions } from 'kea'
import { useEffect } from 'react'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { mswDecorator } from '~/mocks/browser'
import {
    AccessControlLevel,
    type ActionType,
    type EventDefinition,
    type PropertyDefinition,
    PropertyType,
    type UserBasicType,
} from '~/types'

import { DefinitionPopover } from './DefinitionPopover'
import { type DefinitionPopoverLogicProps, definitionPopoverLogic } from './definitionPopoverLogic'

const mockUser: UserBasicType = {
    id: 1,
    uuid: 'user-uuid-123',
    distinct_id: 'user-123',
    first_name: 'Alice',
    email: 'alice@posthog.com',
}

const mockEventDefinition: EventDefinition = {
    id: 'event-uuid-123',
    name: '$pageview',
    description: 'Triggered when a user views a page',
    tags: ['core', 'web'],
    verified: true,
    created_at: '2024-01-15T10:00:00Z',
    owner: mockUser,
    updated_at: '2024-04-20T14:30:00Z',
    updated_by: mockUser,
    last_seen_at: '2024-05-01T09:00:00Z',
}

const mockPropertyDefinition: PropertyDefinition = {
    id: 'prop-uuid-456',
    name: '$current_url',
    description: 'The current URL of the page',
    tags: ['web'],
    is_numerical: false,
    property_type: PropertyType.String,
    verified: true,
    updated_at: '2024-04-25T16:00:00Z',
    updated_by: mockUser,
}

const mockActionDefinition: ActionType = {
    id: 1,
    name: 'User signed up',
    description: 'Tracks when a user completes the signup process',
    tags: ['conversion', 'critical'],
    post_to_slack: false,
    slack_message_format: '',
    steps: [
        {
            event: 'signup_completed',
            properties: [],
        },
    ],
    created_at: '2024-01-05T12:00:00Z',
    created_by: mockUser,
    deleted: false,
    is_calculating: false,
    last_calculated_at: '2024-05-01T00:00:00Z',
    pinned_at: null,
    user_access_level: AccessControlLevel.Editor,
}

const meta: Meta = {
    title: 'Components/Definition popover',
    component: DefinitionPopover.Wrapper,
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/event_definitions/:id': () => [200, mockEventDefinition],
                '/api/projects/:team_id/property_definitions/:id': () => [200, mockPropertyDefinition],
                '/api/projects/:team_id/actions/:id': () => [200, mockActionDefinition],
            },
        }),
    ],
    parameters: {
        mockDate: '2024-05-01 12:00:00',
    },
}
export default meta

interface StoryWrapperProps {
    logicProps: DefinitionPopoverLogicProps
    definition: EventDefinition | PropertyDefinition | ActionType
    icon?: React.ReactNode
    title: React.ReactNode
    headerTitle: React.ReactNode
    editHeaderTitle: React.ReactNode
}

const StoryWrapper: React.FC<StoryWrapperProps> = ({
    logicProps,
    definition,
    icon,
    title,
    headerTitle,
    editHeaderTitle,
}) => {
    const { setDefinition } = useActions(definitionPopoverLogic(logicProps))

    useEffect(() => {
        setDefinition(definition)
    }, [definition, setDefinition])

    const createdAt = 'created_at' in definition ? definition.created_at : undefined
    const createdBy =
        'owner' in definition && definition.owner && typeof definition.owner !== 'boolean'
            ? definition.owner
            : 'created_by' in definition && definition.created_by && typeof definition.created_by !== 'boolean'
              ? definition.created_by
              : undefined
    const updatedAt = 'updated_at' in definition ? definition.updated_at : undefined
    const updatedBy =
        'updated_by' in definition && definition.updated_by && typeof definition.updated_by !== 'boolean'
            ? definition.updated_by
            : undefined

    return (
        <BindLogic logic={definitionPopoverLogic} props={logicProps}>
            <div className="p-4 bg-surface-primary" style={{ width: 400 }}>
                <DefinitionPopover.Wrapper>
                    <DefinitionPopover.Header
                        title={title}
                        headerTitle={headerTitle}
                        editHeaderTitle={editHeaderTitle}
                        icon={icon}
                    />
                    <DefinitionPopover.Description description={definition.description} />
                    <DefinitionPopover.TimeMeta
                        createdAt={createdAt}
                        createdBy={createdBy}
                        updatedAt={updatedAt}
                        updatedBy={updatedBy}
                    />
                </DefinitionPopover.Wrapper>
            </div>
        </BindLogic>
    )
}

const Template: StoryFn<StoryWrapperProps> = (args) => <StoryWrapper {...args} />

export const Event = Template.bind({})
Event.args = {
    logicProps: {
        type: TaxonomicFilterGroupType.Events,
    },
    definition: mockEventDefinition,
    title: mockEventDefinition.name,
    headerTitle: 'Event',
    editHeaderTitle: 'Edit event',
}

export const Property = Template.bind({})
Property.args = {
    logicProps: {
        type: TaxonomicFilterGroupType.EventProperties,
    },
    definition: mockPropertyDefinition,
    title: mockPropertyDefinition.name,
    headerTitle: 'Property',
    editHeaderTitle: 'Edit property',
}

export const Action = Template.bind({})
Action.args = {
    logicProps: {
        type: TaxonomicFilterGroupType.Actions,
    },
    definition: mockActionDefinition,
    title: mockActionDefinition.name,
    headerTitle: 'Action',
    editHeaderTitle: 'Edit action',
}

export const WithoutDescription = Template.bind({})
WithoutDescription.args = {
    logicProps: {
        type: TaxonomicFilterGroupType.Events,
    },
    definition: {
        ...mockEventDefinition,
        description: '',
    },
    title: mockEventDefinition.name,
    headerTitle: 'Event',
    editHeaderTitle: 'Edit event',
}

export const WithMarkdownDescription: StoryFn<StoryWrapperProps> = () => {
    const logicProps: DefinitionPopoverLogicProps = {
        type: TaxonomicFilterGroupType.Events,
    }

    const definitionWithMarkdown: EventDefinition = {
        ...mockEventDefinition,
        description: `## Overview
This event tracks page views across the application.

**Key features:**
- Automatically captured on all pages
- Includes referrer information
- Contains page metadata

\`\`\`javascript
posthog.capture('$pageview', { url: window.location.href })
\`\`\``,
    }

    return (
        <StoryWrapper
            logicProps={logicProps}
            definition={definitionWithMarkdown}
            title={definitionWithMarkdown.name}
            headerTitle="Event"
            editHeaderTitle="Edit event"
        />
    )
}

export const WithoutTimestamps = Template.bind({})
WithoutTimestamps.args = {
    logicProps: {
        type: TaxonomicFilterGroupType.Events,
    },
    definition: {
        id: 'event-new',
        name: 'new_event',
        description: 'A newly created event with no timestamps',
        tags: [],
    } as EventDefinition,
    title: 'new_event',
    headerTitle: 'Event',
    editHeaderTitle: 'Edit event',
}

export const ComponentShowcase: StoryFn = () => {
    return (
        <div className="flex flex-col gap-8 p-4 bg-surface-primary">
            <div>
                <h3 className="text-lg font-semibold mb-2">Description - String</h3>
                <DefinitionPopover.Description description="This is a simple text description" />
            </div>

            <div>
                <h3 className="text-lg font-semibold mb-2">Description - Markdown</h3>
                <DefinitionPopover.Description description="**Bold text** and *italic text* with [links](https://posthog.com)" />
            </div>

            <div>
                <h3 className="text-lg font-semibold mb-2">Description empty</h3>
                <BindLogic logic={definitionPopoverLogic} props={{ type: TaxonomicFilterGroupType.Events }}>
                    <DefinitionPopover.DescriptionEmpty />
                </BindLogic>
            </div>

            <div>
                <h3 className="text-lg font-semibold mb-2">Time meta - With update</h3>
                <DefinitionPopover.TimeMeta
                    createdAt="2024-01-15T10:00:00Z"
                    createdBy={mockUser}
                    updatedAt="2024-04-20T14:30:00Z"
                    updatedBy={mockUser}
                />
            </div>

            <div>
                <h3 className="text-lg font-semibold mb-2">Time meta - Only created</h3>
                <DefinitionPopover.TimeMeta createdAt="2024-01-15T10:00:00Z" createdBy={mockUser} />
            </div>

            <div>
                <h3 className="text-lg font-semibold mb-2">Horizontal line</h3>
                <DefinitionPopover.HorizontalLine />
            </div>

            <div>
                <h3 className="text-lg font-semibold mb-2">Horizontal line - With label</h3>
                <DefinitionPopover.HorizontalLine label="Metadata" />
            </div>

            <div>
                <h3 className="text-lg font-semibold mb-2">Grid - 2 columns</h3>
                <DefinitionPopover.Grid cols={2}>
                    <DefinitionPopover.Card title="First seen" value="2024-01-15" />
                    <DefinitionPopover.Card title="Last seen" value="2024-05-01" />
                </DefinitionPopover.Grid>
            </div>

            <div>
                <h3 className="text-lg font-semibold mb-2">Section (Grid - 1 column)</h3>
                <DefinitionPopover.Section>
                    <DefinitionPopover.Card title="Property type" value="String" />
                </DefinitionPopover.Section>
            </div>

            <div>
                <h3 className="text-lg font-semibold mb-2">Card - With alignItems</h3>
                <DefinitionPopover.Card title="Aligned to center" value="Center value" alignItems="center" />
            </div>
        </div>
    )
}
