import { MOCK_DEFAULT_TEAM, MOCK_TEAM_ID } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { RestrictionType } from 'lib/logic/eventIngestionRestrictionLogic'
import { teamLogic } from 'scenes/teamLogic'

import { useStorybookMocks } from '~/mocks/browser'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { FeatureFlagPersonlessWarning } from './FeatureFlagPersonlessWarning'

type StoryProps = { optedOut: boolean; restricted?: boolean; withCohort?: boolean }

const PROPERTIES: AnyPropertyFilter[] = [
    { key: 'email', type: PropertyFilterType.Person, operator: PropertyOperator.IContains, value: '@posthog.com' },
    { key: 'plan', type: PropertyFilterType.Person, operator: PropertyOperator.Exact, value: 'enterprise' },
]

const COHORT_PROPERTY: AnyPropertyFilter = {
    key: 'id',
    type: PropertyFilterType.Cohort,
    value: 12,
    operator: PropertyOperator.In,
}

const meta: Meta<(props: StoryProps) => JSX.Element> = {
    title: 'Scenes-App/Feature Flags/Personless Warning',
    parameters: { layout: 'padded', viewMode: 'story' },
    render: ({ optedOut, restricted, withCohort }: StoryProps) => {
        useStorybookMocks({
            get: {
                [`/api/environments/${MOCK_TEAM_ID}/event_ingestion_restrictions/`]: () => [
                    200,
                    restricted ? [{ restriction_type: RestrictionType.SKIP_PERSON_PROCESSING }] : [],
                ],
            },
        })
        const { loadCurrentTeamSuccess } = useActions(teamLogic)
        useEffect(() => {
            loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, person_processing_opt_out: optedOut })
        }, [loadCurrentTeamSuccess, optedOut])

        return <FeatureFlagPersonlessWarning properties={withCohort ? [...PROPERTIES, COHORT_PROPERTY] : PROPERTIES} />
    },
}
export default meta

type Story = StoryObj<(props: StoryProps) => JSX.Element>

export const ProjectOptedOut: Story = {
    args: { optedOut: true },
}

export const ProjectOptedOutWithCohort: Story = {
    args: { optedOut: true, withCohort: true },
}

export const IngestionRestriction: Story = {
    args: { optedOut: false, restricted: true },
}
