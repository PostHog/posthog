import { LemonButton, LemonDivider, LemonTag, lemonToast, Link } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import { FlagSelector } from 'lib/components/FlagSelector'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { useEffect } from 'react'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'
import { FeatureFlagReleaseConditions } from 'scenes/feature-flags/FeatureFlagReleaseConditions'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { FeatureFlagFilters, Survey, SurveyMatchType } from '~/types'

import { LOADING_SURVEY_RESULTS_TOAST_ID, NewSurvey, SurveyMatchTypeLabels } from './constants'
import SurveyEdit from './SurveyEdit'
import { surveyLogic } from './surveyLogic'
import { SurveyView } from './SurveyView'

export const scene: SceneExport = {
    component: SurveyComponent,
    logic: surveyLogic,
    paramsToProps: ({ params: { id } }): (typeof surveyLogic)['props'] => ({
        id: id,
    }),
    settingSectionId: 'environment-surveys',
}

export function SurveyComponent({ id }: { id?: string } = {}): JSX.Element {
    const { editingSurvey, setSelectedPageIndex } = useActions(surveyLogic)
    const { isEditingSurvey, surveyMissing } = useValues(surveyLogic)

    /**
     * Logic that cleans up surveyLogic state when the component unmounts.
     * Necessary so if we load another survey, we don't have the old survey's state in the logic for things like editing, filters, preview, etc.
     */
    useEffect(() => {
        return () => {
            editingSurvey(false)
            setSelectedPageIndex(0)
            lemonToast.dismiss(LOADING_SURVEY_RESULTS_TOAST_ID)
        }
    }, [editingSurvey, setSelectedPageIndex])

    if (surveyMissing) {
        return <NotFound object="survey" />
    }

    return (
        <div>
            {!id ? (
                <LemonSkeleton />
            ) : (
                <BindLogic logic={surveyLogic} props={{ id }}>
                    {isEditingSurvey ? <SurveyForm id={id} /> : <SurveyView id={id} />}
                </BindLogic>
            )}
        </div>
    )
}

export function SurveyForm({ id }: { id: string }): JSX.Element {
    const { survey, surveyLoading, targetingFlagFilters } = useValues(surveyLogic)
    const { loadSurvey, editingSurvey } = useActions(surveyLogic)

    const handleCancelClick = (): void => {
        editingSurvey(false)
        if (id === 'new') {
            router.actions.push(urls.surveys())
        } else {
            loadSurvey()
        }
    }

    return (
        <Form
            id="survey"
            formKey="survey"
            logic={surveyLogic}
            props={{ id }}
            className="deprecated-space-y-4"
            enableFormOnSubmit
        >
            <PageHeader
                buttons={
                    <div className="flex items-center gap-2">
                        <LemonButton
                            data-attr="cancel-survey"
                            type="secondary"
                            loading={surveyLoading}
                            onClick={handleCancelClick}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            data-attr="save-survey"
                            htmlType="submit"
                            loading={surveyLoading}
                            form="survey"
                        >
                            {id === 'new' ? 'Save as draft' : 'Save'}
                        </LemonButton>
                    </div>
                }
            />
            <LemonDivider />
            <SurveyEdit />
            <LemonDivider />
            <SurveyDisplaySummary id={id} survey={survey} targetingFlagFilters={targetingFlagFilters} />
            <LemonDivider />
        </Form>
    )
}

export function SurveyDisplaySummary({
    id,
    survey,
    targetingFlagFilters,
}: {
    id: string
    survey: Survey | NewSurvey
    targetingFlagFilters?: FeatureFlagFilters
}): JSX.Element {
    const hasConditions =
        survey.conditions?.url ||
        survey.conditions?.selector ||
        survey.conditions?.seenSurveyWaitPeriodInDays ||
        (survey.conditions?.events?.values.length ?? 0) > 0
    const hasFeatureFlags = survey.linked_flag_id || targetingFlagFilters

    return (
        <div className="flex flex-col mt-2 gap-2">
            <div className="font-semibold">Display conditions summary</div>
            <span className="text-secondary">
                {hasConditions || hasFeatureFlags
                    ? 'Surveys will be displayed to users that match the following conditions:'
                    : 'Surveys will be displayed to everyone.'}
            </span>
            {survey.conditions?.url && (
                <div className="flex flex-col font-medium gap-1">
                    <div className="flex-row">
                        <span>
                            URL{' '}
                            {SurveyMatchTypeLabels[survey.conditions?.urlMatchType || SurveyMatchType.Contains].slice(
                                2
                            )}
                            :
                        </span>{' '}
                        <LemonTag>{survey.conditions.url}</LemonTag>
                    </div>
                </div>
            )}
            {survey.conditions?.deviceTypes && (
                <div className="flex font-medium gap-1 items-center">
                    <span>
                        Device Types{' '}
                        {SurveyMatchTypeLabels[
                            survey.conditions?.deviceTypesMatchType || SurveyMatchType.Contains
                        ].slice(2)}
                        :
                    </span>{' '}
                    {survey.conditions.deviceTypes.map((type) => (
                        <LemonTag key={type}>{type}</LemonTag>
                    ))}
                </div>
            )}
            {survey.conditions?.selector && (
                <div className="flex flex-col font-medium gap-1">
                    <div className="flex-row">
                        <span>Selector matches:</span> <LemonTag>{survey.conditions.selector}</LemonTag>
                    </div>
                </div>
            )}
            {survey.linked_flag_id && (
                <div className="flex flex-row font-medium gap-1">
                    <span>Feature flag enabled for:</span>{' '}
                    {id !== 'new' ? (
                        survey.linked_flag?.id ? (
                            <>
                                <Link to={urls.featureFlag(survey.linked_flag?.id)}>{survey.linked_flag?.key}</Link>
                                {survey.conditions?.linkedFlagVariant && (
                                    <LemonTag>variant: {survey.conditions.linkedFlagVariant}</LemonTag>
                                )}
                            </>
                        ) : null
                    ) : (
                        <>
                            <FlagSelector value={survey.linked_flag_id} readOnly={true} onChange={() => {}} />
                            {survey.conditions?.linkedFlagVariant && (
                                <LemonTag>variant: {survey.conditions.linkedFlagVariant}</LemonTag>
                            )}
                        </>
                    )}
                </div>
            )}
            {survey.conditions?.seenSurveyWaitPeriodInDays && (
                <div className="flex flex-col font-medium gap-1">
                    <div className="flex-row">
                        <span>Wait period after seeing survey:</span>{' '}
                        <LemonTag>
                            {survey.conditions.seenSurveyWaitPeriodInDays}{' '}
                            {survey.conditions.seenSurveyWaitPeriodInDays === 1 ? 'day' : 'days'}
                        </LemonTag>
                    </div>
                </div>
            )}
            {targetingFlagFilters && (
                <div>
                    <BindLogic logic={featureFlagLogic} props={{ id: survey.targeting_flag?.id || 'new' }}>
                        <span className="font-medium">User properties:</span>{' '}
                        <FeatureFlagReleaseConditions readOnly excludeTitle filters={targetingFlagFilters} />
                    </BindLogic>
                </div>
            )}
            {(survey.conditions?.events?.values.length ?? 0) > 0 && (
                <div className="flex flex-col font-medium gap-1">
                    <div className="flex-row">
                        <span>
                            When the user sends the following events (
                            <span>
                                {survey.conditions?.events?.repeatedActivation
                                    ? 'every time they occur'
                                    : 'once per user'}
                            </span>
                            ):
                        </span>
                        {survey.conditions?.events?.values.map((event) => (
                            <LemonTag key={event.name}>{event.name}</LemonTag>
                        ))}
                    </div>
                </div>
            )}
        </div>
    )
}
