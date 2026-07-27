import { useActions, useAsyncActions, useValues } from 'kea'

import { IconRewind } from '@posthog/icons'
import { LemonDialog, LemonInput } from '@posthog/lemon-ui'

import { SceneMenuBarFileItems } from 'lib/components/Scenes/SceneMenuBarFileItems'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { isUUIDLike } from 'lib/utils/guards'
import { PersonsManagementSceneTabs } from 'scenes/persons-management/PersonsManagementSceneTabs'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneMenuBar, SceneMenuBarItem, SceneMenuBarMenu } from '~/layout/scenes/components/SceneMenuBar'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ScenePanel, ScenePanelActionsSection } from '~/layout/scenes/SceneLayout'
import { Query } from '~/queries/Query/Query'
import { ActorsQuery, ProductKey } from '~/queries/schema/schema-general'
import { ActivityTab, CustomerProfileScope, OnboardingStepKey } from '~/types'

import { FeedbackButton } from 'products/customer_analytics/frontend/components/FeedbackButton'
import { PersonDisplayNameNudgeBanner } from 'products/customer_analytics/frontend/components/PersonDisplayNameNudgeBanner'
import { customerProfileConfigLogic } from 'products/customer_analytics/frontend/customerProfileConfigLogic'

import { personsSceneLogic } from './personsSceneLogic'

export const scene: SceneExport = {
    component: PersonsScene,
    logic: personsSceneLogic,
    productKey: ProductKey.PRODUCT_ANALYTICS,
}

export function PersonsScene(): JSX.Element {
    const { query } = useValues(personsSceneLogic)
    const { setQuery } = useActions(personsSceneLogic)
    const { resetDeletedDistinctId } = useAsyncActions(personsSceneLogic)
    const { currentTeam, baseCurrency } = useValues(teamLogic)
    const { loadConfigs } = useActions(customerProfileConfigLogic({ scope: CustomerProfileScope.PERSON }))
    const queryUniqueKey = 'persons-query'
    const sceneMenuBarEnabled = useFeatureFlag('SCENE_MENU_BAR')

    // A UUID-shaped search that returns nothing is often a session ID typed into the wrong field.
    // Session IDs aren't part of the persons query, so point the user to where they are searchable.
    const rawSearch: unknown = (query.source as Partial<ActorsQuery> | undefined)?.search
    const searchTerm = typeof rawSearch === 'string' ? rawSearch.trim() : undefined
    const searchLooksLikeSessionId = !!searchTerm && isUUIDLike(searchTerm)

    useOnMountEffect(() => {
        loadConfigs()
    })

    const onResetDeletedPerson = (): void => {
        LemonDialog.openForm({
            width: '30rem',
            title: 'Reset deleted person',
            description: `Once a person is deleted, the "distinct_id" associated with them can no longer be used.
                You can use this tool to reset the "distinct_id" for a person so that new events associated with it will create a new Person profile.`,
            initialValues: { distinct_id: '' },
            content: (
                <LemonField name="distinct_id" label="Distinct ID to reset">
                    <LemonInput type="text" autoFocus />
                </LemonField>
            ),
            errors: {
                distinct_id: (distinct_id) => (!distinct_id ? 'This is required' : undefined),
            },
            onSubmit: async ({ distinct_id }) => await resetDeletedDistinctId(distinct_id),
        })
    }

    return (
        <SceneContent>
            <PersonsManagementSceneTabs tabKey="persons" />

            {sceneMenuBarEnabled && (
                <SceneMenuBar>
                    <SceneMenuBarMenu label="File" dataAttr="persons-menubar-file">
                        <SceneMenuBarFileItems dataAttrKey="persons" />
                        <SceneMenuBarItem
                            variant="destructive"
                            opensFloatingUi
                            onClick={onResetDeletedPerson}
                            data-attr="persons-menubar-reset-deleted"
                        >
                            <IconRewind />
                            Reset a deleted person
                        </SceneMenuBarItem>
                    </SceneMenuBarMenu>
                </SceneMenuBar>
            )}

            <SceneTitleSection
                name={sceneConfigurations[Scene.Persons].name}
                description={sceneConfigurations[Scene.Persons].description}
                resourceType={{
                    type: sceneConfigurations[Scene.Persons].iconType || 'default_icon_type',
                }}
                actions={
                    <>
                        <FeedbackButton id="customer-analytics-people-list-feedback-button" />
                        <ScenePanel>
                            <ScenePanelActionsSection>
                                <ButtonPrimitive
                                    menuItem
                                    variant="danger"
                                    onClick={() => {
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
                                            onSubmit: async ({ distinct_id }) =>
                                                await resetDeletedDistinctId(distinct_id),
                                        })
                                    }}
                                >
                                    <IconRewind />
                                    Reset a deleted person...
                                </ButtonPrimitive>
                            </ScenePanelActionsSection>
                        </ScenePanel>
                    </>
                }
            />
            <PersonDisplayNameNudgeBanner uniqueKey={queryUniqueKey} />

            <Query
                uniqueKey={queryUniqueKey}
                attachTo={personsSceneLogic()}
                query={{ ...query, showCount: true, showTableViews: true }}
                setQuery={setQuery}
                context={{
                    refresh: 'blocking',
                    emptyStateHeading:
                        currentTeam?.ingested_event && searchLooksLikeSessionId
                            ? 'Looking for a session?'
                            : currentTeam?.ingested_event
                              ? 'There are no matching persons for this query'
                              : 'No persons exist because no events have been ingested',
                    emptyStateDetail:
                        currentTeam?.ingested_event && searchLooksLikeSessionId ? (
                            <>
                                Session IDs can't be searched here. Open it directly in{' '}
                                <Link to={urls.replaySingle(searchTerm!)}>Session replay</Link>, or search sessions on
                                the <Link to={urls.activity(ActivityTab.ExploreSessions)}>Activity</Link> page. To find
                                a person instead, search by name, email, person ID, or distinct ID.
                            </>
                        ) : currentTeam?.ingested_event ? (
                            <>
                                This page only shows{' '}
                                <Link to="https://posthog.com/docs/data/persons">identified persons</Link>. Try
                                adjusting your property filters, or make sure you're calling{' '}
                                <Link to="https://posthog.com/docs/product-analytics/identify">identify</Link> in your
                                app.
                            </>
                        ) : (
                            <>
                                Go to the{' '}
                                <Link
                                    to={urls.onboarding({
                                        productKey: ProductKey.PRODUCT_ANALYTICS,
                                        stepKey: OnboardingStepKey.INSTALL,
                                    })}
                                    data-attr="real_project_with_no_events-ingestion_link"
                                >
                                    onboarding flow
                                </Link>{' '}
                                to get things moving
                            </>
                        ),
                    baseCurrency,
                }}
                dataAttr="persons-table"
            />
        </SceneContent>
    )
}
