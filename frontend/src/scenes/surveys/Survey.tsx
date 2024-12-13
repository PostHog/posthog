import { LemonButton, LemonDivider, LemonTag, Link } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import { FlagSelector } from 'lib/components/FlagSelector'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'
import { FeatureFlagReleaseConditions } from 'scenes/feature-flags/FeatureFlagReleaseConditions'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { FeatureFlagFilters, Survey, SurveyUrlMatchType } from '~/types'

import { NewSurvey, SurveyUrlMatchTypeLabels } from './constants'
import SurveyEdit from './SurveyEdit'
import { surveyLogic } from './surveyLogic'
import { SurveyView } from './SurveyView'

export const scene: SceneExport = {
    component: SurveyComponent,
    logic: surveyLogic,
    paramsToProps: ({ params: { id } }): (typeof surveyLogic)['props'] => ({
        id: id,
    }),
}

export function SurveyComponent({ id }: { id?: string } = {}): JSX.Element {
    const { isEditingSurvey, surveyMissing } = useValues(surveyLogic)

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
        <Form id="survey" formKey="survey" logic={surveyLogic} props={{ id }} className="space-y-4" enableFormOnSubmit>
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
        survey.conditions?.url || survey.conditions?.selector || survey.conditions?.seenSurveyWaitPeriodInDays
    const hasFeatureFlags = survey.linked_flag_id || targetingFlagFilters

    return (
        <div className="flex flex-col mt-2 gap-2">
            <div className="font-semibold">Display conditions summary</div>
            <span className="text-muted">
                {hasConditions || hasFeatureFlags
                    ? 'Surveys will be displayed to users that match the following conditions:'
                    : 'Surveys will be displayed to everyone.'}
            </span>
            {survey.conditions?.url && (
                <div className="flex flex-col font-medium gap-1">
                    <div className="flex-row">
                        <span>
                            URL{' '}
                            {SurveyUrlMatchTypeLabels[
                                survey.conditions?.urlMatchType || SurveyUrlMatchType.Contains
                            ].slice(2)}
                            :
                        </span>{' '}
                        <LemonTag>{survey.conditions.url}</LemonTag>
                    </div>
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
                            <Link to={urls.featureFlag(survey.linked_flag?.id)}>{survey.linked_flag?.key}</Link>
                        ) : null
                    ) : (
                        <FlagSelector value={survey.linked_flag_id} readOnly={true} onChange={() => {}} />
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
                <BindLogic logic={featureFlagLogic} props={{ id: survey.targeting_flag?.id || 'new' }}>
                    <span className="font-medium">User properties:</span>{' '}
                    <FeatureFlagReleaseConditions readOnly excludeTitle filters={targetingFlagFilters} />
                </BindLogic>
            )}
        </div>
    )
}
