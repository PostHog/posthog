import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInput, LemonMenu } from '@posthog/lemon-ui'
import { useActions, useAsyncActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { personsSceneLogic } from 'scenes/persons-management/tabs/personsSceneLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { ProductKey, OnboardingStepKey } from '~/types'

export function Persons(): JSX.Element {
    const { query } = useValues(personsSceneLogic)
    const { setQuery } = useActions(personsSceneLogic)
    const { resetDeletedDistinctId } = useAsyncActions(personsSceneLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <>
            <PageHeader
                buttons={
                    <LemonMenu
                        items={[
                            {
                                label: 'Reset a deleted person...',
                                onClick: () =>
                                    LemonDialog.openForm({
                                        width: '30rem',
                                        title: 'Reset deleted person',
                                        description: `Once a person is deleted, the "distinct_id" associated with them can no longer be used. 
                                            You can use this tool to reset the "distinct_id" for a person so that new events associated with it will create a new Person profile.`,
                                        initialValues: {
                                            distinct_id: '',
                                        },
                                        content: (
                                            <LemonField name="distinct_id" label="Distinct ID to reset">
                                                <LemonInput type="text" autoFocus />
                                            </LemonField>
                                        ),
                                        errors: {
                                            distinct_id: (distinct_id) =>
                                                !distinct_id ? 'This is required' : undefined,
                                        },
                                        onSubmit: async ({ distinct_id }) => await resetDeletedDistinctId(distinct_id),
                                    }),
                            },
                        ]}
                    >
                        <LemonButton aria-label="more" icon={<IconEllipsis />} size="small" />
                    </LemonMenu>
                }
            />
            <Query
                query={query}
                setQuery={setQuery}
                context={{
                    refresh: 'blocking',
                    emptyStateHeading: currentTeam?.ingested_event
                        ? 'There are no matching persons for this query'
                        : 'No persons exist because no events have been ingested',
                    emptyStateDetail: currentTeam?.ingested_event ? (
                        'Try changing the date range or property filters.'
                    ) : (
                        <>
                            Go to the{' '}
                            <Link
                                to={urls.onboarding(ProductKey.PRODUCT_ANALYTICS, OnboardingStepKey.INSTALL)}
                                data-attr="real_project_with_no_events-ingestion_link"
                            >
                                onboarding wizard
                            </Link>{' '}
                            to get things moving
                        </>
                    ),
                }}
                dataAttr="persons-table"
            />
        </>
    )
}
