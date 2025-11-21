import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonLabel, LemonModal, LemonTextArea, lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { addProductIntent } from 'lib/utils/product-intents'
import { AddEventButton } from 'scenes/surveys/AddEventButton'
import { SurveyAppearancePreview } from 'scenes/surveys/SurveyAppearancePreview'
import { SurveyPopupToggle } from 'scenes/surveys/SurveySettings'
import { NewSurvey, SURVEY_CREATED_SOURCE, defaultSurveyAppearance } from 'scenes/surveys/constants'
import { surveysLogic } from 'scenes/surveys/surveysLogic'
import { urls } from 'scenes/urls'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { FeatureFlagType, PropertyDefinitionType, Survey, SurveyQuestionType, SurveyType } from '~/types'

export interface QuickSurveyFormProps {
    flag: FeatureFlagType
    onCancel?: () => void
}

export function QuickSurveyForm({ flag, onCancel }: QuickSurveyFormProps): JSX.Element {
    const flagName = flag.name || flag.key
    const [question, setQuestion] = useState(`You're trying our latest new feature. What do you think?`)
    const [targetVariant, setTargetVariant] = useState<string | null>(null)
    const [targetUrl, setTargetUrl] = useState<string>('')
    const [selectedEvents, setSelectedEvents] = useState<string[]>([])
    const [isCreating, setIsCreating] = useState(false)

    const { showSurveysDisabledBanner } = useValues(surveysLogic)
    const { loadSurveys } = useActions(surveysLogic)
    const { reportSurveyCreated } = useActions(eventUsageLogic)
    const { options } = useValues(propertyDefinitionsModel)
    const { loadPropertyValues } = useActions(propertyDefinitionsModel)

    const shouldShowSurveyToggle = useRef(!!showSurveysDisabledBanner).current

    const variants = flag.filters?.multivariate?.variants || []
    const isMultivariate = variants.length > 1
    const urlOptions = options['$current_url']

    useEffect(() => {
        if (urlOptions?.status !== 'loading' && urlOptions?.status !== 'loaded') {
            loadPropertyValues({
                endpoint: undefined,
                type: PropertyDefinitionType.Event,
                propertyKey: '$current_url',
                newInput: '',
                eventNames: [],
                properties: [],
            })
        }
    }, [urlOptions?.status, loadPropertyValues])

    const buildSurveyData = useCallback(
        (launch: boolean): Partial<Survey> => {
            const randomId = Math.random().toString(36).substring(2, 8)
            return {
                name: `${flagName}${targetVariant ? ` (${targetVariant})` : ''} - Quick feedback #${randomId}`,
                type: SurveyType.Popover,
                questions: [
                    {
                        type: SurveyQuestionType.Open,
                        question: question.trim(),
                        optional: false,
                    },
                ],
                conditions: {
                    actions: null,
                    events: {
                        values: selectedEvents.map((name) => ({ name })),
                    },
                    ...(targetVariant ? { linkedFlagVariant: targetVariant } : {}),
                    ...(targetUrl ? { url: targetUrl } : {}),
                },
                linked_flag_id: flag.id,
                appearance: defaultSurveyAppearance,
                ...(launch ? { start_date: dayjs().toISOString() } : {}),
            }
        },
        [flagName, question, targetVariant, targetUrl, selectedEvents, flag.id]
    )

    const previewSurvey: NewSurvey = useMemo(
        () =>
            ({
                ...buildSurveyData(false),
                id: 'new',
                created_at: '',
                created_by: null,
            }) as NewSurvey,
        [buildSurveyData]
    )

    const handleCreate = async ({ createType }: { createType: 'launch' | 'edit' | 'draft' }): Promise<void> => {
        if (!question.trim()) {
            return
        }

        const shouldLaunch = createType === 'launch'
        setIsCreating(true)
        try {
            const surveyData = buildSurveyData(shouldLaunch)
            const response = await api.surveys.create(surveyData)

            reportSurveyCreated(response)
            addProductIntent({
                product_type: ProductKey.SURVEYS,
                intent_context: ProductIntentContext.SURVEY_CREATED,
                metadata: {
                    survey_id: response.id,
                    source: SURVEY_CREATED_SOURCE.FEATURE_FLAGS,
                    created_successfully: true,
                    quick_survey: true,
                    create_mode: createType,
                },
            })

            lemonToast.success(shouldLaunch ? 'Survey created and launched!' : 'Survey created as draft')
            router.actions.push(`${urls.survey(response.id)}${createType === 'edit' ? '?edit=true' : ''}`)
            if (onCancel) {
                onCancel()
            }
        } catch (error) {
            lemonToast.error('Failed to create survey')
            console.error('Survey creation error:', error)
        } finally {
            setIsCreating(false)
            loadSurveys()
        }
    }

    return (
        <>
            <div className="grid grid-cols-2 gap-6">
                <div className="space-y-4">
                    <div>
                        <LemonLabel className="mb-2">Question for users</LemonLabel>
                        <LemonTextArea
                            value={question}
                            onChange={(value) => setQuestion(value)}
                            placeholder="What do you think?"
                            minRows={2}
                            data-attr="quick-survey-question-input"
                        />
                    </div>

                    {isMultivariate && (
                        <div>
                            <LemonLabel>Who should see this survey?</LemonLabel>
                            <div className="space-y-2 mt-2">
                                <label className="flex items-center gap-2 cursor-pointer">
                                    <input
                                        type="radio"
                                        checked={targetVariant === null}
                                        onChange={() => setTargetVariant(null)}
                                        className="cursor-pointer"
                                    />
                                    <span className="text-sm">All users with this flag enabled</span>
                                </label>
                                {variants.map((v) => (
                                    <label key={v.key} className="flex items-center gap-2 cursor-pointer">
                                        <input
                                            type="radio"
                                            checked={targetVariant === v.key}
                                            onChange={() => setTargetVariant(v.key)}
                                            className="cursor-pointer"
                                        />
                                        <span className="text-sm">
                                            Only users in the <code className="text-xs">{v.key}</code> variant
                                        </span>
                                    </label>
                                ))}
                            </div>
                        </div>
                    )}

                    <div>
                        <LemonLabel className="mb-2">Target specific URL (optional)</LemonLabel>
                        <LemonInputSelect
                            mode="single"
                            value={targetUrl ? [targetUrl] : []}
                            onChange={(val) => setTargetUrl(val[0] || '')}
                            onInputChange={(newInput) => {
                                loadPropertyValues({
                                    type: PropertyDefinitionType.Event,
                                    endpoint: undefined,
                                    propertyKey: '$current_url',
                                    newInput: newInput.trim(),
                                    eventNames: [],
                                    properties: [],
                                })
                            }}
                            placeholder="All URLs"
                            allowCustomValues
                            loading={urlOptions?.status === 'loading'}
                            options={(urlOptions?.values || []).map(({ name }) => ({
                                key: String(name),
                                label: String(name),
                                value: String(name),
                            }))}
                            data-attr="quick-survey-url-input"
                        />
                    </div>

                    <div>
                        <LemonLabel className="mb-2">Trigger on events (optional)</LemonLabel>
                        {selectedEvents.length > 0 && (
                            <div className="space-y-2 mb-2">
                                {selectedEvents.map((eventName) => (
                                    <div
                                        key={eventName}
                                        className="flex items-center justify-between p-2 border rounded bg-bg-light"
                                    >
                                        <span className="text-sm font-medium">{eventName}</span>
                                        <LemonButton
                                            size="xsmall"
                                            icon={<IconX />}
                                            onClick={() =>
                                                setSelectedEvents(selectedEvents.filter((e) => e !== eventName))
                                            }
                                            type="tertiary"
                                            status="alt"
                                        />
                                    </div>
                                ))}
                            </div>
                        )}
                        <AddEventButton
                            onEventSelect={(eventName) => setSelectedEvents([...selectedEvents, eventName])}
                            excludedEvents={selectedEvents}
                        />
                    </div>
                </div>

                <div>
                    <div className="mt-2 p-4 bg-secondary-highlight min-h-[300px] flex items-center justify-center">
                        <SurveyAppearancePreview survey={previewSurvey} previewPageIndex={0} />
                    </div>
                </div>
            </div>

            <div className="mt-6">
                {shouldShowSurveyToggle && (
                    <div className="mb-4 p-4 border rounded bg-warning-highlight">
                        <SurveyPopupToggle />
                    </div>
                )}

                <div className="flex justify-between items-end">
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => handleCreate({ createType: 'edit' })}
                        loading={isCreating}
                        disabledReason={!question.trim() ? 'Enter a question' : undefined}
                        data-attr="quick-survey-advanced"
                    >
                        Open in advanced editor
                    </LemonButton>
                    <div className="flex gap-2">
                        {onCancel && (
                            <LemonButton onClick={onCancel} type="secondary" data-attr="quick-survey-cancel">
                                Cancel
                            </LemonButton>
                        )}
                        <LemonButton
                            type="primary"
                            onClick={() => handleCreate({ createType: 'launch' })}
                            loading={isCreating}
                            disabledReason={!question.trim() ? 'Enter a question' : undefined}
                            data-attr="quick-survey-create"
                            sideAction={{
                                dropdown: {
                                    placement: 'bottom-end',
                                    overlay: (
                                        <LemonMenuOverlay
                                            items={[
                                                {
                                                    label: 'Save as draft',
                                                    onClick: () => handleCreate({ createType: 'draft' }),
                                                },
                                            ]}
                                        />
                                    ),
                                },
                            }}
                        >
                            Create & launch
                        </LemonButton>
                    </div>
                </div>
            </div>
        </>
    )
}

export interface QuickSurveyModalProps {
    flag: FeatureFlagType
    isOpen: boolean
    onClose: () => void
}

export function QuickSurveyModal({ flag, isOpen, onClose }: QuickSurveyModalProps): JSX.Element {
    return (
        <LemonModal title="Quick feedback survey" isOpen={isOpen} onClose={onClose} width={900}>
            <QuickSurveyForm flag={flag} onCancel={onClose} />
        </LemonModal>
    )
}
