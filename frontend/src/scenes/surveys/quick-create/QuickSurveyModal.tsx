import { BindLogic, useActions, useValues } from 'kea'
import { useMemo, useRef } from 'react'

import { LemonButton, LemonInput, LemonLabel, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { SurveyAppearancePreview } from 'scenes/surveys/SurveyAppearancePreview'
import { SurveyPopupToggle } from 'scenes/surveys/SurveySettings'
import { teamLogic } from 'scenes/teamLogic'

import { SurveyQuestionType } from '~/types'

import { EventSelector } from './components/EventSelector'
import { FunnelSequence } from './components/FunnelSequence'
import { URLInput } from './components/URLInput'
import { VariantSelector } from './components/VariantSelector'
import {
    DEFAULT_RATING_LOWER_LABEL,
    DEFAULT_RATING_UPPER_LABEL,
    QuickSurveyCreateMode,
    QuickSurveyFormLogicProps,
    quickSurveyFormLogic,
} from './quickSurveyFormLogic'
import { QuickSurveyFormProps, QuickSurveyType } from './types'
import { buildLogicProps } from './utils'

export function QuickSurveyForm({ context, onCancel }: QuickSurveyFormProps): JSX.Element {
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
    const shouldShowSurveyToggle = useRef(!currentTeam?.surveys_opt_in).current

    const handleSubmit = (mode: QuickSurveyCreateMode): void => {
        setCreateMode(mode)
    }

    return (
        <>
            <div className="grid grid-cols-2 gap-6">
                <div className="space-y-4">
                    <div>
                        <LemonLabel className="mb-2">Question for users</LemonLabel>
                        <LemonTextArea
                            value={surveyForm.question}
                            onChange={(value) => setSurveyFormValue('question', value)}
                            placeholder="What do you think?"
                            minRows={2}
                            data-attr="quick-survey-question-input"
                        />
                    </div>

                    {surveyForm.questionType === SurveyQuestionType.Rating && (
                        <div className="grid grid-cols-2 gap-4">
                            <div>
                                <LemonLabel className="mb-2">Low rating label</LemonLabel>
                                <LemonInput
                                    value={surveyForm.ratingLowerBound || ''}
                                    onChange={(value) => setSurveyFormValue('ratingLowerBound', value)}
                                    placeholder={DEFAULT_RATING_LOWER_LABEL}
                                />
                            </div>
                            <div>
                                <LemonLabel className="mb-2">High rating label</LemonLabel>
                                <LemonInput
                                    value={surveyForm.ratingUpperBound || ''}
                                    onChange={(value) => setSurveyFormValue('ratingUpperBound', value)}
                                    placeholder={DEFAULT_RATING_UPPER_LABEL}
                                />
                            </div>
                        </div>
                    )}

                    <BindLogic logic={quickSurveyFormLogic} props={logicProps}>
                        {context.type === QuickSurveyType.FEATURE_FLAG && (
                            <>
                                <VariantSelector variants={context.flag.filters?.multivariate?.variants || []} />
                                <EventSelector />
                            </>
                        )}

                        {context.type === QuickSurveyType.EXPERIMENT && (
                            <>
                                <VariantSelector
                                    variants={context.experiment.parameters?.feature_flag_variants || []}
                                    defaultOptionText="All users exposed to this experiment"
                                />
                                <EventSelector />
                            </>
                        )}

                        {context.type === QuickSurveyType.FUNNEL && (
                            <>
                                <FunnelSequence steps={context.funnel.steps} />
                            </>
                        )}

                        <URLInput />
                    </BindLogic>
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
        </>
    )
}

export function QuickSurveyModal({
    context,
    onCancel,
    isOpen,
}: QuickSurveyFormProps & { isOpen: boolean }): JSX.Element {
    return (
        <LemonModal title="Quick feedback survey" isOpen={isOpen} onClose={onCancel} width={900}>
            <QuickSurveyForm context={context} onCancel={onCancel} />
        </LemonModal>
    )
}
