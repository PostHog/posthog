import { JSONContent } from '@tiptap/core'
import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { uploadFile } from 'lib/hooks/useUploadFiles'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'

import { Survey, SurveyType } from '~/types'

import { surveysLogic } from '../surveysLogic'
import { toSurveyQuestions } from './components/questions/formQuestionAdapter'
import { FormContentStorage } from './formTypes'
import type { surveyFormBuilderLogicType } from './surveyFormBuilderLogicType'

export interface SurveyFormBuilderLogicProps {
    id: string // 'new' for new surveys, or a UUID for editing
}

const NEW_SURVEY_FORM: FormContentStorage = {
    content: null,
    showLogo: false,
    showCover: false,
    coverColor: '#E8CCBF',
    logoUrl: null,
    logoMediaId: null,
    coverImageUrl: null,
    coverImageMediaId: null,
    coverImagePosition: { x: 50, y: 50 },
}

export function extractNameFromContent(content: JSONContent): string {
    if (content.content) {
        for (const node of content.content) {
            if (node.type === 'heading' && node.content) {
                const text = node.content
                    .filter((n) => n.type === 'text')
                    .map((n) => n.text || '')
                    .join('')
                if (text.trim()) {
                    return text.trim()
                }
            }
        }
    }
    return 'Untitled form'
}

export const surveyFormBuilderLogic = kea<surveyFormBuilderLogicType>([
    path(['scenes', 'surveys', 'form', 'surveyFormBuilderLogic']),

    props({} as SurveyFormBuilderLogicProps),

    key((props) => props.id),

    connect(() => ({
        actions: [surveysLogic, ['loadSurveys'], eventUsageLogic, ['reportSurveyCreated', 'reportSurveyEdited']],
        values: [surveysLogic, ['formBuilderEnabled'], organizationLogic, ['currentOrganization']],
    })),

    actions({
        toggleCover: true,
        uploadImage: (file: File, target: 'logo' | 'cover') => ({ file, target }),
        uploadImageSuccess: (url: string, mediaId: string, target: 'logo' | 'cover') => ({ url, mediaId, target }),
        uploadImageFailure: (error: string, target: 'logo' | 'cover') => ({ error, target }),
        addLogo: true,
        removeLogo: true,
        removeCoverImage: true,
        removeCover: true,
        launchSurvey: true,
        launchSurveySuccess: (survey: Survey) => ({ survey }),
        launchSurveyFailure: (error: string) => ({ error }),
    }),

    loaders(({ props }) => ({
        existingSurvey: [
            null as Survey | null,
            {
                loadExistingSurvey: async () => {
                    return await api.surveys.get(props.id)
                },
            },
        ],
    })),

    forms(({ values, props, actions }) => ({
        surveyForm: {
            defaults: NEW_SURVEY_FORM,
            submit: async (form) => {
                const formPayload: Partial<Survey> = {
                    name: values.surveyName,
                    questions: values.surveyQuestions,
                    form_content: form.content ? form : null,
                }

                try {
                    const saved = values.isEditing
                        ? await api.surveys.update(props.id, formPayload)
                        : await api.surveys.create({ ...formPayload, type: SurveyType.ExternalSurvey })

                    actions.loadExistingSurveySuccess(saved)
                    lemonToast.success(`Survey "${saved.name}" saved`)
                    actions.loadSurveys()
                    if (values.isEditing) {
                        actions.reportSurveyEdited(saved)
                    } else {
                        actions.reportSurveyCreated(saved)
                        router.actions.replace(urls.surveyFormBuilder(saved.id))
                    }
                } catch (e) {
                    posthog.captureException(e, {
                        surveyId: formPayload.id,
                    })
                    lemonToast.error('Failed to save survey')
                    throw e
                }
            },
        },
    })),

    reducers({
        existingSurvey: {
            launchSurveySuccess: (_, { survey }) => survey,
        },
        imageUploading: [
            {} as Record<string, boolean>,
            {
                uploadImage: (state, { target }) => ({ ...state, [target]: true }),
                uploadImageSuccess: (state, { target }) => ({ ...state, [target]: false }),
                uploadImageFailure: (state, { target }) => ({ ...state, [target]: false }),
            },
        ],
        surveyLaunching: [
            false,
            {
                launchSurvey: () => true,
                launchSurveySuccess: () => false,
                launchSurveyFailure: () => false,
            },
        ],
    }),

    selectors({
        isEditing: [() => [(_, props) => props.id], (id: string): boolean => id !== 'new'],
        surveyName: [
            (s) => [s.surveyForm],
            (surveyForm: FormContentStorage): string => {
                if (!surveyForm.content) {
                    return 'Untitled form'
                }
                return extractNameFromContent(surveyForm.content)
            },
        ],
        surveyQuestions: [
            (s) => [s.surveyForm],
            (surveyForm: FormContentStorage) => {
                if (!surveyForm.content) {
                    return []
                }
                return toSurveyQuestions(surveyForm.content)
            },
        ],
        hasRealContent: [
            (s) => [s.surveyForm],
            (surveyForm: FormContentStorage): boolean => {
                if (!surveyForm.content?.content) {
                    return false
                }

                return surveyForm.content.content.some((node, index) => {
                    if (index === 0) {
                        return false
                    }
                    if (node.type === 'formButton') {
                        return false
                    }
                    if (node.type === 'paragraph' && (!node.content || node.content.length === 0)) {
                        return false
                    }
                    return true
                })
            },
        ],
        logoUploading: [
            (s) => [s.imageUploading],
            (imageUploading: Record<string, boolean>): boolean => !!imageUploading['logo'],
        ],
        coverImageUploading: [
            (s) => [s.imageUploading],
            (imageUploading: Record<string, boolean>): boolean => !!imageUploading['cover'],
        ],
    }),

    listeners(({ actions, values, props }) => ({
        addLogo: () => {
            const org = values.currentOrganization
            if (org?.logo_media_id) {
                actions.setSurveyFormValues({ logoMediaId: org.logo_media_id })
            }
            actions.setSurveyFormValues({ showLogo: true })
        },
        toggleCover: () => {
            actions.setSurveyFormValues({ showCover: !values.surveyForm.showCover })
        },
        removeLogo: () => {
            actions.setSurveyFormValues({ showLogo: false, logoUrl: null, logoMediaId: null })
        },
        removeCoverImage: () => {
            actions.setSurveyFormValues({
                coverImageUrl: null,
                coverImageMediaId: null,
                coverImagePosition: { x: 50, y: 50 },
            })
        },
        removeCover: () => {
            actions.setSurveyFormValues({
                showCover: false,
                coverColor: '#E8CCBF',
                coverImageUrl: null,
                coverImageMediaId: null,
                coverImagePosition: { x: 50, y: 50 },
            })
        },
        uploadImage: async ({ file, target }) => {
            try {
                const media = await uploadFile(file)
                actions.uploadImageSuccess(media.image_location, media.id, target)
                if (target === 'logo') {
                    actions.setSurveyFormValues({ showLogo: true })
                } else {
                    actions.setSurveyFormValues({ showCover: true })
                }
            } catch (e) {
                actions.uploadImageFailure(String(e), target)
                lemonToast.error(`Failed to upload ${target} image`)
            }
        },
        uploadImageSuccess: ({ url, mediaId, target }) => {
            if (target === 'logo') {
                actions.setSurveyFormValues({ logoUrl: url, logoMediaId: mediaId })
            } else {
                actions.setSurveyFormValues({ coverImageUrl: url, coverImageMediaId: mediaId })
            }
        },
        loadExistingSurveySuccess: ({ existingSurvey }) => {
            if (existingSurvey?.form_content) {
                actions.setSurveyFormValues(existingSurvey.form_content)
            }
        },
        loadExistingSurveyFailure: () => {
            lemonToast.error('Failed to load survey')
        },
        launchSurvey: async () => {
            try {
                const formPayload: Partial<Survey> = {
                    name: values.surveyName,
                    questions: values.surveyQuestions,
                    form_content: values.surveyForm.content ? values.surveyForm : null,
                    start_date: dayjs().toISOString(),
                }
                const launched = values.isEditing
                    ? await api.surveys.update(props.id, formPayload)
                    : await api.surveys.create({ ...formPayload, type: SurveyType.ExternalSurvey })
                actions.launchSurveySuccess(launched)
            } catch (e) {
                actions.launchSurveyFailure(String(e))
                lemonToast.error('Failed to launch survey')
            }
        },
        launchSurveySuccess: ({ survey }) => {
            lemonToast.success(`Survey "${survey.name}" launched`)
            actions.loadSurveys()
            if (values.isEditing) {
                actions.reportSurveyEdited(survey)
            } else {
                actions.reportSurveyCreated(survey)
            }
            router.actions.replace(urls.survey(survey.id))
        },
    })),

    urlToAction(({ values, props }) => ({
        [urls.surveyFormBuilder(props.id)]: () => {
            if (!values.formBuilderEnabled) {
                router.actions.replace(urls.survey(props.id))
            }
        },
    })),

    afterMount(({ actions, props }) => {
        if (props.id !== 'new') {
            actions.loadExistingSurvey()
        }
    }),
])
