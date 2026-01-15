import { BindLogic, useActions, useValues } from 'kea'
import { SurveyQuestionType } from 'posthog-js'
import { useMemo, useRef } from 'react'

import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonLabel,
    LemonModal,
    LemonSwitch,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { SurveyAppearancePreview } from 'scenes/surveys/SurveyAppearancePreview'
import { SurveyPopupToggle } from 'scenes/surveys/SurveySettings'
import { SdkVersionWarnings } from 'scenes/surveys/components/SdkVersionWarnings'
import { getSurveyWarnings } from 'scenes/surveys/surveyVersionRequirements'
import { surveysSdkLogic } from 'scenes/surveys/surveysSdkLogic'
import { teamLogic } from 'scenes/teamLogic'

import { Survey } from '~/types'

import { EventSelector } from './quick-create/components/EventSelector'
import { ExceptionFilters } from './quick-create/components/ExceptionFilters'
import { FunnelSequence } from './quick-create/components/FunnelSequence'
import { URLInput } from './quick-create/components/URLInput'
import { VariantSelector } from './quick-create/components/VariantSelector'
import {
    DEFAULT_RATING_LOWER_LABEL,
    DEFAULT_RATING_UPPER_LABEL,
    QuickSurveyCreateMode,
    QuickSurveyFormLogicProps,
    quickSurveyFormLogic,
} from './quick-create/quickSurveyFormLogic'
import { QuickSurveyFormProps, QuickSurveyType } from './quick-create/types'
import { buildLogicProps } from './quick-create/utils'

export function QuickSurveyForm({ context, info, onCancel, showFollowupToggle }: QuickSurveyFormProps): JSX.Element {
    const logicProps: QuickSurveyFormLogicProps = useMemo(() => {
        return {
            ...buildLogicProps(context),
            onSuccess: onCancel,
        }
    }, [context, onCancel])

    const { surveyForm, previewSurvey, isSurveyFormSubmitting, submitDisabledReason } = useValues(
        quickSurveyFormLogic(logicProps)
    )
    const { setSurveyFormValue, setCreateMode } = useActions(quickSurveyFormLogic(logicProps))

    const { currentTeam } = useValues(teamLogic)
    const { teamSdkVersions } = useValues(surveysSdkLogic)
    const shouldShowSurveyToggle = useRef(!currentTeam?.surveys_opt_in).current

    const warnings = useMemo(
        () => getSurveyWarnings(previewSurvey as Survey, teamSdkVersions),
        [previewSurvey, teamSdkVersions]
    )

    const handleSubmit = (mode: QuickSurveyCreateMode): void => {
        setCreateMode(mode)
    }

    return (
        <BindLogic logic={quickSurveyFormLogic} props={logicProps}>
            {info && <LemonBanner type="info">{info}</LemonBanner>}

            <div className="grid grid-cols-2 gap-6 mt-2">
                <div className="space-y-4">
                    {context.type !== QuickSurveyType.ANNOUNCEMENT && (
                        <div>
                            <LemonLabel className="mb-2">Ask your users</LemonLabel>
                            <LemonTextArea
                                value={surveyForm.question}
                                onChange={(value) => setSurveyFormValue('question', value)}
                                placeholder="What do you think?"
                                minRows={2}
                                data-attr="quick-survey-question-input"
                                onFocus={(e) => e.currentTarget.select()}
                            />
                        </div>
                    )}

                    {context.type === QuickSurveyType.ANNOUNCEMENT && (
                        <>
                            <div>
                                <LemonLabel className="mb-2">Title</LemonLabel>
                                <LemonInput
                                    value={surveyForm.question}
                                    onChange={(value) => setSurveyFormValue('question', value)}
                                    placeholder="Hog mode is now available!"
                                    data-attr="quick-survey-question-input"
                                    onFocus={(e) => e.currentTarget.select()}
                                />
                            </div>

                            <div>
                                <LemonLabel className="mb-2">Description</LemonLabel>
                                <LemonTextArea
                                    value={surveyForm.description}
                                    onChange={(value) => setSurveyFormValue('description', value)}
                                    placeholder="You can never have too many hedgehogs."
                                    minRows={2}
                                    data-attr="quick-survey-question-input"
                                    onFocus={(e) => e.currentTarget.select()}
                                />
                            </div>

                            <div className="grid grid-cols-2 gap-4">
                                <div>
                                    <LemonLabel className="mb-2">Button text</LemonLabel>
                                    <LemonInput
                                        value={surveyForm.buttonText}
                                        onChange={(value) => setSurveyFormValue('buttonText', value)}
                                        placeholder="Check it out 👉"
                                        data-attr="quick-survey-question-input"
                                        onFocus={(e) => e.currentTarget.select()}
                                    />
                                </div>
                                <div>
                                    <LemonLabel className="mb-2">Button link</LemonLabel>
                                    <LemonInput
                                        value={surveyForm.link}
                                        placeholder="Optional"
                                        onChange={(value) => setSurveyFormValue('link', value)}
                                        data-attr="quick-survey-question-input"
                                    />
                                </div>
                            </div>
                        </>
                    )}

                    {surveyForm.questionType === SurveyQuestionType.Rating && (
                        <div className="grid grid-cols-2 gap-4">
                            <div>
                                <LemonLabel className="mb-2">Low rating label</LemonLabel>
                                <LemonInput
                                    value={surveyForm.ratingLowerBound || ''}
                                    onChange={(value) => setSurveyFormValue('ratingLowerBound', value)}
                                    placeholder={DEFAULT_RATING_LOWER_LABEL}
                                    onFocus={(e) => e.currentTarget.select()}
                                />
                            </div>
                            <div>
                                <LemonLabel className="mb-2">High rating label</LemonLabel>
                                <LemonInput
                                    value={surveyForm.ratingUpperBound || ''}
                                    onChange={(value) => setSurveyFormValue('ratingUpperBound', value)}
                                    placeholder={DEFAULT_RATING_UPPER_LABEL}
                                    onFocus={(e) => e.currentTarget.select()}
                                />
                            </div>
                        </div>
                    )}

                    {showFollowupToggle && (
                        <>
                            <div className="flex items-center gap-2">
                                <LemonSwitch
                                    checked={!!surveyForm.followUpEnabled}
                                    onChange={(checked) => setSurveyFormValue('followUpEnabled', checked)}
                                    label="Ask a follow-up question"
                                />
                            </div>
                            {surveyForm.followUpEnabled && (
                                <div className="mt-2">
                                    <LemonTextArea
                                        value={surveyForm.followUpQuestion || ''}
                                        onChange={(value) => setSurveyFormValue('followUpQuestion', value)}
                                        placeholder="Tell us more (optional)"
                                        minRows={2}
                                    />
                                </div>
                            )}
                        </>
                    )}

                    {context.type === QuickSurveyType.FEATURE_FLAG && (
                        <>
                            <VariantSelector variants={context.flag.filters?.multivariate?.variants || []} />
                            <EventSelector />
                            <URLInput />
                        </>
                    )}

                    {context.type === QuickSurveyType.FUNNEL && <FunnelSequence steps={context.funnel.steps} />}

                    {context.type === QuickSurveyType.EXPERIMENT && (
                        <>
                            <VariantSelector
                                variants={context.experiment.parameters?.feature_flag_variants || []}
                                defaultOptionText="All users exposed to this experiment"
                            />
                            <EventSelector />
                            <URLInput />
                        </>
                    )}

                    {context.type === QuickSurveyType.ERROR_TRACKING && <URLInput />}
                </div>

                <div>
                    <div className="mt-2 p-4 bg-secondary-highlight min-h-[300px] flex items-center justify-center">
                        <SurveyAppearancePreview survey={previewSurvey} previewPageIndex={0} />
                    </div>
                </div>
            </div>

            {context.type === QuickSurveyType.ERROR_TRACKING && <ExceptionFilters />}

            <div className="flex flex-col gap-3 mt-4">
                {shouldShowSurveyToggle && (
                    <div className="p-4 border rounded bg-warning-highlight">
                        <SurveyPopupToggle />
                    </div>
                )}

                <SdkVersionWarnings warnings={warnings} />

                {submitDisabledReason && (
                    <LemonBanner type="error" className="mb-4">
                        {submitDisabledReason}
                    </LemonBanner>
                )}

                <div className="flex justify-between items-end">
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => handleSubmit('edit')}
                        loading={isSurveyFormSubmitting}
                        disabledReason={submitDisabledReason}
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
                            onClick={() => handleSubmit('launch')}
                            loading={isSurveyFormSubmitting}
                            disabledReason={submitDisabledReason}
                            data-attr="quick-survey-create"
                            sideAction={{
                                dropdown: {
                                    placement: 'bottom-end',
                                    overlay: (
                                        <LemonMenuOverlay
                                            items={[
                                                {
                                                    label: 'Save as draft',
                                                    onClick: () => handleSubmit('draft'),
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
        </BindLogic>
    )
}

export function QuickSurveyModal({
    context,
    info,
    onCancel,
    isOpen,
    modalTitle,
    showFollowupToggle,
}: {
    context?: QuickSurveyFormProps['context']
    info?: QuickSurveyFormProps['info']
    onCancel: () => void
    isOpen: boolean
    modalTitle?: string
    showFollowupToggle?: boolean
}): JSX.Element {
    return (
        <LemonModal title={modalTitle || 'Quick feedback survey'} isOpen={isOpen} onClose={onCancel} width={900}>
            {context && (
                <QuickSurveyForm
                    context={context}
                    info={info}
                    onCancel={onCancel}
                    showFollowupToggle={showFollowupToggle}
                />
            )}
        </LemonModal>
    )
}
