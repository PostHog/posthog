import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useEffect } from 'react'

import { LemonDivider, LemonTag, Link, lemonToast } from '@posthog/lemon-ui'

import { FlagSelector } from 'lib/components/FlagSelector'
import { NotFound } from 'lib/components/NotFound'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { FeatureFlagReleaseConditions } from 'scenes/feature-flags/FeatureFlagReleaseConditions'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { FeatureFlagFilters, Survey, SurveyMatchType } from '~/types'

import SurveyEdit from './SurveyEdit'
import { SurveyView } from './SurveyView'
import { LOADING_SURVEY_RESULTS_TOAST_ID, NewSurvey, SurveyMatchTypeLabels } from './constants'
import { SurveyLogicProps, surveyLogic } from './surveyLogic'

export const scene: SceneExport<SurveyLogicProps> = {
    component: SurveyComponent,
    logic: surveyLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
    settingSectionId: 'environment-surveys',
}

export function SurveyComponent({ id }: SurveyLogicProps): JSX.Element {
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
    const { survey, targetingFlagFilters } = useValues(surveyLogic)

    return (
        <Form
            id="survey"
            formKey="survey"
            logic={surveyLogic}
            props={{ id }}
            className="deprecated-space-y-4"
            enableFormOnSubmit
        >
            <SurveyEdit id={id} />
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
    const hasFeatureFlags = survey.linked_flag_id || survey.linked_flag || targetingFlagFilters

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
            {(survey.linked_flag_id || survey.linked_flag) && (
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
                            <FlagSelector value={survey.linked_flag_id || 0} readOnly={true} onChange={() => {}} />
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
