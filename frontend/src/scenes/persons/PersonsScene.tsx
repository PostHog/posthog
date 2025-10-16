import { useActions, useAsyncActions, useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInput, LemonMenu } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { PersonsManagementSceneTabs } from 'scenes/persons-management/PersonsManagementSceneTabs'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { Query } from '~/queries/Query/Query'
import { OnboardingStepKey, ProductKey } from '~/types'

import { personsSceneLogic } from './personsSceneLogic'

export const scene: SceneExport = {
    component: PersonsScene,
    logic: personsSceneLogic,
}

export function PersonsScene({ tabId }: { tabId?: string } = {}): JSX.Element {
    if (!tabId) {
        // TODO: sometimes when opening a property filter on a scene, the tabId is suddently empty.
        // If I remove the "{closable && !disabledReason && ...}" block from within
        // "frontend/src/lib/components/PropertyFilters/components/PropertyFilterButton.tsx"
        // ... then the issue goes away. We should still figure out why this happens.
        // Throwing seems to make it go away.
        throw new Error('PersonsScene rendered with no tabId')
    }

    const { query } = useValues(personsSceneLogic)
    const { setQuery } = useActions(personsSceneLogic)
    const { resetDeletedDistinctId } = useAsyncActions(personsSceneLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <SceneContent>
            <PersonsManagementSceneTabs tabKey="persons" />

            <SceneTitleSection
                name={sceneConfigurations[Scene.Persons].name}
                description={sceneConfigurations[Scene.Persons].description}
                resourceType={{
                    type: sceneConfigurations[Scene.Persons].iconType || 'default_icon_type',
                }}
                actions={
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
            <SceneDivider />

            <Query
                uniqueKey={`persons-query-${tabId}`}
                attachTo={personsSceneLogic({ tabId })}
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
        </SceneContent>
    )
}
