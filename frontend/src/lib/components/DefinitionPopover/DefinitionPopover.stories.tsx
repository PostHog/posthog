import { Meta, StoryFn } from '@storybook/react'
import { BindLogic } from 'kea'
import { useRef } from 'react'

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

import {
    eventTaxonomicGroupProps,
    propertyTaxonomicGroupProps,
    taxonomicFilterLogic,
} from '../TaxonomicFilter/taxonomicFilterLogic'
import { ControlledDefinitionPopover } from './DefinitionPopoverContents'
import { type DefinitionPopoverLogicProps, definitionPopoverLogic } from './definitionPopoverLogic'

const mockUser: UserBasicType = {
    id: 1,
    uuid: 'user-uuid-123',
    distinct_id: 'user-123',
    first_name: 'Alice',
    email: 'alice@posthog.com',
}

const mockEventImages = [
    'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNjAwIiBoZWlnaHQ9IjQwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iNjAwIiBoZWlnaHQ9IjQwMCIgZmlsbD0iI2UwZjJmZSIvPjx0ZXh0IHg9IjUwJSIgeT0iNTAlIiBmb250LWZhbWlseT0iQXJpYWwiIGZvbnQtc2l6ZT0iMjQiIGZpbGw9IiMzMzMiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGRvbWluYW50LWJhc2VsaW5lPSJtaWRkbGUiPlNjcmVlbnNob3QgMTwvdGV4dD48L3N2Zz4=',
    'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNjAwIiBoZWlnaHQ9IjQwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iNjAwIiBoZWlnaHQ9IjQwMCIgZmlsbD0iI2ZlZTJlMiIvPjx0ZXh0IHg9IjUwJSIgeT0iNTAlIiBmb250LWZhbWlseT0iQXJpYWwiIGZvbnQtc2l6ZT0iMjQiIGZpbGw9IiMzMzMiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGRvbWluYW50LWJhc2VsaW5lPSJtaWRkbGUiPlNjcmVlbnNob3QgMjwvdGV4dD48L3N2Zz4=',
    'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNjAwIiBoZWlnaHQ9IjQwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iNjAwIiBoZWlnaHQ9IjQwMCIgZmlsbD0iI2UwZmVlOCIvPjx0ZXh0IHg9IjUwJSIgeT0iNTAlIiBmb250LWZhbWlseT0iQXJpYWwiIGZvbnQtc2l6ZT0iMjQiIGZpbGw9IiMzMzMiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGRvbWluYW50LWJhc2VsaW5lPSJtaWRkbGUiPlNjcmVlbnNob3QgMzwvdGV4dD48L3N2Zz4=',
]

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
    media_preview_urls: mockEventImages,
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
    component: ControlledDefinitionPopover,
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
    item: EventDefinition | PropertyDefinition | ActionType
    groupType: TaxonomicFilterGroupType
}

const StoryWrapper: React.FC<StoryWrapperProps> = ({ logicProps, item, groupType }) => {
    const divRef = useRef<HTMLDivElement>(null)

    const group = {
        name: groupType,
        searchPlaceholder: '',
        type: groupType,
        getValue: (instance: any) => instance.name,
        ...(groupType === TaxonomicFilterGroupType.Events
            ? eventTaxonomicGroupProps
            : groupType === TaxonomicFilterGroupType.EventProperties
              ? propertyTaxonomicGroupProps()
              : {
                    getPopoverHeader: () => 'Action',
                    getIcon: undefined,
                }),
    }

    const taxonomicFilterLogicProps = {
        taxonomicFilterLogicKey: 'definition-popover-story',
        taxonomicGroupTypes: [groupType],
    }

    return (
        <BindLogic logic={definitionPopoverLogic} props={logicProps}>
            <BindLogic logic={taxonomicFilterLogic} props={taxonomicFilterLogicProps}>
                <div className="p-4 bg-surface-primary" style={{ width: 400, height: 600 }}>
                    <div ref={divRef} className="p-2 border border-border rounded">
                        Hover target
                    </div>
                    <ControlledDefinitionPopover
                        visible={true}
                        item={item}
                        group={group}
                        highlightedItemElement={divRef.current}
                    />
                </div>
            </BindLogic>
        </BindLogic>
    )
}

const Template: StoryFn<StoryWrapperProps> = (args) => <StoryWrapper {...args} />

export const Event = Template.bind({})
Event.args = {
    logicProps: {
        type: TaxonomicFilterGroupType.Events,
    },
    item: mockEventDefinition,
    groupType: TaxonomicFilterGroupType.Events,
}

export const Property = Template.bind({})
Property.args = {
    logicProps: {
        type: TaxonomicFilterGroupType.EventProperties,
    },
    item: mockPropertyDefinition,
    groupType: TaxonomicFilterGroupType.EventProperties,
}

export const Action = Template.bind({})
Action.args = {
    logicProps: {
        type: TaxonomicFilterGroupType.Actions,
    },
    item: mockActionDefinition,
    groupType: TaxonomicFilterGroupType.Actions,
}

export const WithoutDescription = Template.bind({})
WithoutDescription.args = {
    logicProps: {
        type: TaxonomicFilterGroupType.Events,
    },
    item: {
        ...mockEventDefinition,
        description: '',
    },
    groupType: TaxonomicFilterGroupType.Events,
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
            item={definitionWithMarkdown}
            groupType={TaxonomicFilterGroupType.Events}
        />
    )
}

export const WithoutTimestamps = Template.bind({})
WithoutTimestamps.args = {
    logicProps: {
        type: TaxonomicFilterGroupType.Events,
    },
    item: {
        id: 'event-new',
        name: 'new_event',
        description: 'A newly created event with no timestamps',
        tags: [],
    } as EventDefinition,
    groupType: TaxonomicFilterGroupType.Events,
}
