import { SceneExport } from 'scenes/sceneTypes'
import { surveyLogic } from './surveyLogic'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonButton, LemonInput, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { Field } from 'lib/forms/Field'
import { SurveyType } from '~/types'

export const scene: SceneExport = {
    component: Survey,
    logic: surveyLogic,
    paramsToProps: ({ params: { id } }): (typeof surveyLogic)['props'] => ({
        id: id,
    }),
}

export function Survey({ id }: { id?: string } = {}): JSX.Element {
    const { isEditingSurvey } = useValues(surveyLogic)
    const showSurveyForm = id === 'new' || isEditingSurvey
    return <div>{!id ? <LemonSkeleton /> : <>{showSurveyForm ? <SurveyForm id={id} /> : <SurveyView />}</>}</div>
}

export function SurveyForm({ id }: { id: string }): JSX.Element {
    const { survey, surveyLoading, isEditingSurvey } = useValues(surveyLogic)
    const { loadSurvey, editingSurvey } = useActions(surveyLogic)
    return (
        <Form formKey="survey" logic={surveyLogic}>
            <PageHeader
                title={id === 'new' ? 'New survey' : survey.name}
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
                        >
                            Save
                        </LemonButton>
                    </div>
                }
            />
            <Field name="name" label="Name">
                <LemonInput data-attr="survey-name" />
            </Field>
            <Field name="description" label="Description">
                <LemonTextArea data-attr="survey-description" />
            </Field>
            <Field name="type" label="Type">
                <LemonSelect data-attr="survey-type" options={[{ label: 'Popover', value: SurveyType.Popover }]} />
            </Field>
        </Form>
    )
}

export function SurveyView(): JSX.Element {
    return <div>survey view</div>
}
