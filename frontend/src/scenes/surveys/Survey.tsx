import { LemonButton, LemonDivider, Link } from '@posthog/lemon-ui'
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

import { Survey, SurveyUrlMatchType } from '~/types'

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
    const showSurveyForm = id === 'new' || isEditingSurvey

    if (surveyMissing) {
        return <NotFound object="survey" />
    }

    return (
        <div>
            {!id ? (
                <LemonSkeleton />
            ) : (
                <BindLogic logic={surveyLogic} props={{ id }}>
                    {showSurveyForm ? <SurveyForm id={id} /> : <SurveyView id={id} />}
                </BindLogic>
            )}
        </div>
    )
}

export function SurveyForm({ id }: { id: string }): JSX.Element {
    const { survey, surveyLoading, isEditingSurvey, hasTargetingFlag } = useValues(surveyLogic)
    const { loadSurvey, editingSurvey } = useActions(surveyLogic)

    return (
        <Form id="survey" formKey="survey" logic={surveyLogic} className="space-y-4" enableFormOnSubmit>
            <PageHeader
                buttons={
                    <div className="flex items-center gap-2">
                        <LemonButton
                            data-attr="cancel-survey"
                            type="secondary"
                            loading={surveyLoading}
                            onClick={() => {
                                if (isEditingSurvey) {
                                    editingSurvey(false)
                                    loadSurvey()
                                } else {
                                    router.actions.push(urls.surveys())
                                }
                            }}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            data-attr="save-feature-flag"
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
            <SurveyReleaseSummary id={id} survey={survey} hasTargetingFlag={hasTargetingFlag} />
            <LemonDivider />
            <div className="flex items-center gap-2 justify-end">
                <LemonButton
                    data-attr="cancel-survey"
                    type="secondary"
                    loading={surveyLoading}
                    onClick={() => {
                        if (isEditingSurvey) {
                            editingSurvey(false)
                            loadSurvey()
                        } else {
                            router.actions.push(urls.surveys())
                        }
                    }}
                >
                    Cancel
                </LemonButton>
                <LemonButton type="primary" data-attr="save-survey" htmlType="submit" loading={surveyLoading}>
                    {id === 'new' ? 'Save as draft' : 'Save'}
                </LemonButton>
            </div>
        </Form>
    )
}

export function SurveyReleaseSummary({
    id,
    survey,
    hasTargetingFlag,
}: {
    id: string
    survey: Survey | NewSurvey
    hasTargetingFlag: boolean
}): JSX.Element {
    return (
        <div className="flex flex-col mt-2 gap-2">
            <div className="font-semibold">Release conditions summary</div>
            <span className="text-muted">
                By default surveys will be released to everyone unless targeting options are set.
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
                        <span className="simple-tag tag-light-blue text-primary-alt">{survey.conditions.url}</span>
                    </div>
                </div>
            )}
            {survey.conditions?.selector && (
                <div className="flex flex-col font-medium gap-1">
                    <div className="flex-row">
                        <span>Selector matches:</span>{' '}
                        <span className="simple-tag tag-light-blue text-primary-alt">{survey.conditions.selector}</span>
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
            <BindLogic logic={featureFlagLogic} props={{ id: survey.targeting_flag?.id || 'new' }}>
                {hasTargetingFlag && (
                    <>
                        <span className="font-medium">User properties:</span>{' '}
                        <FeatureFlagReleaseConditions readOnly excludeTitle />
                    </>
                )}
            </BindLogic>
        </div>
    )
}
