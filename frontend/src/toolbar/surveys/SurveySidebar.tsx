import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconArchive, IconEllipsis, IconExternal, IconPlus, IconRocket, IconTrash, IconX } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton } from '@posthog/lemon-ui'

import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { joinWithUiHost } from '~/toolbar/utils'
import { SurveyMatchType } from '~/types'

import { SIDEBAR_WIDTH } from './constants'
import { SurveyLivePreview } from './SurveyLivePreview'
import {
    clampDelaySeconds,
    FREQUENCY_OPTIONS,
    getSurveyStatus,
    type QuickSurveyQuestionType,
    SURVEY_CHOICE_MAX_LENGTH,
    SURVEY_DELAY_MAX_SECONDS,
    SURVEY_NAME_MAX_LENGTH,
    SURVEY_QUESTION_MAX_LENGTH,
    SURVEY_QUICK_FORM_MAX_CHOICES,
    surveysToolbarLogic,
} from './surveysToolbarLogic'

const SIDEBAR_TRANSITION_MS = 200
const SIDEBAR_Z_INDEX = 2147483019

const QUESTION_TYPE_OPTIONS = [
    { value: 'open' as const, label: 'Open text' },
    { value: 'rating' as const, label: 'Rating scale' },
    { value: 'single_choice' as const, label: 'Single choice' },
]

const URL_MATCH_TYPE_OPTIONS: { value: SurveyMatchType; label: string }[] = [
    { value: SurveyMatchType.Exact, label: 'Exact' },
    { value: SurveyMatchType.Contains, label: 'Contains' },
    { value: SurveyMatchType.Regex, label: 'Regex' },
]

function QuestionSection(): JSX.Element {
    const { quickForm } = useValues(surveysToolbarLogic)
    const { setFormField } = useActions(surveysToolbarLogic)

    return (
        <section>
            <h3 className="text-xs font-semibold text-muted-3000 uppercase tracking-wide mb-3">Question</h3>
            <div className="space-y-3">
                <div>
                    <label className="text-xs font-medium text-muted mb-0.5 block">Survey name</label>
                    <LemonInput
                        placeholder="e.g. Feedback on checkout"
                        fullWidth
                        size="small"
                        maxLength={SURVEY_NAME_MAX_LENGTH}
                        value={quickForm.name}
                        onChange={(v) => setFormField('name', v)}
                    />
                </div>

                <div>
                    <label className="text-xs font-medium text-muted mb-0.5 block">Question type</label>
                    <LemonSelect
                        fullWidth
                        size="small"
                        options={QUESTION_TYPE_OPTIONS}
                        value={quickForm.questionType}
                        onChange={(v) => setFormField('questionType', v as QuickSurveyQuestionType)}
                    />
                </div>

                <div>
                    <label className="text-xs font-medium text-muted mb-0.5 block">Question text</label>
                    <LemonTextArea
                        placeholder="What would you like to ask?"
                        value={quickForm.questionText}
                        onChange={(v) => setFormField('questionText', v.slice(0, SURVEY_QUESTION_MAX_LENGTH))}
                        minRows={2}
                        maxRows={4}
                    />
                </div>

                {quickForm.questionType === 'rating' && (
                    <>
                        <div>
                            <label className="text-xs font-medium text-muted mb-0.5 block">Scale</label>
                            <LemonSelect
                                fullWidth
                                size="small"
                                options={[
                                    { value: 5, label: '1–5' },
                                    { value: 10, label: '1–10 (NPS)' },
                                ]}
                                value={quickForm.ratingScale}
                                onChange={(v) => setFormField('ratingScale', v)}
                            />
                        </div>
                        <div className="flex gap-2">
                            <div className="flex-1">
                                <label className="text-xs font-medium text-muted mb-0.5 block">Low label</label>
                                <LemonInput
                                    size="small"
                                    fullWidth
                                    maxLength={SURVEY_NAME_MAX_LENGTH}
                                    value={quickForm.ratingLowerLabel}
                                    onChange={(v) => setFormField('ratingLowerLabel', v)}
                                />
                            </div>
                            <div className="flex-1">
                                <label className="text-xs font-medium text-muted mb-0.5 block">High label</label>
                                <LemonInput
                                    size="small"
                                    fullWidth
                                    maxLength={SURVEY_NAME_MAX_LENGTH}
                                    value={quickForm.ratingUpperLabel}
                                    onChange={(v) => setFormField('ratingUpperLabel', v)}
                                />
                            </div>
                        </div>
                    </>
                )}

                {quickForm.questionType === 'single_choice' && (
                    <div>
                        <label className="text-xs font-medium text-muted mb-0.5 block">Choices</label>
                        <div className="space-y-1">
                            {quickForm.choices.map((choice, i) => (
                                <div key={i} className="flex gap-1 items-center">
                                    <LemonInput
                                        size="small"
                                        fullWidth
                                        placeholder={`Option ${i + 1}`}
                                        maxLength={SURVEY_CHOICE_MAX_LENGTH}
                                        value={choice}
                                        onChange={(v) => {
                                            const newChoices = [...quickForm.choices]
                                            newChoices[i] = v
                                            setFormField('choices', newChoices)
                                        }}
                                    />
                                    {quickForm.choices.length > 2 && (
                                        <LemonButton
                                            size="xsmall"
                                            icon={<IconTrash />}
                                            onClick={() => {
                                                const newChoices = quickForm.choices.filter((_, j) => j !== i)
                                                setFormField('choices', newChoices)
                                            }}
                                        />
                                    )}
                                </div>
                            ))}
                            {quickForm.choices.length < SURVEY_QUICK_FORM_MAX_CHOICES && (
                                <LemonButton
                                    size="xsmall"
                                    type="secondary"
                                    icon={<IconPlus />}
                                    fullWidth
                                    onClick={() => setFormField('choices', [...quickForm.choices, ''])}
                                >
                                    Add option
                                </LemonButton>
                            )}
                        </div>
                    </div>
                )}
            </div>
        </section>
    )
}

function WhereSection(): JSX.Element {
    const { quickForm } = useValues(surveysToolbarLogic)
    const { setFormField } = useActions(surveysToolbarLogic)

    return (
        <section>
            <h3 className="text-xs font-semibold text-muted-3000 uppercase tracking-wide mb-3">Where</h3>
            <div className="space-y-3">
                <div>
                    <LemonRadio
                        value={quickForm.targetingMode}
                        onChange={(v) => setFormField('targetingMode', v)}
                        options={[
                            {
                                value: 'all',
                                label: 'All pages',
                                description: 'Survey can appear anywhere on your site',
                            },
                            {
                                value: 'specific',
                                label: 'Specific pages',
                                description: 'Only show on pages matching a URL pattern',
                            },
                        ]}
                    />
                    {quickForm.targetingMode === 'specific' && (
                        <div className="mt-2 ml-6 space-y-2">
                            <div className="flex gap-1 items-center">
                                <LemonInput
                                    size="small"
                                    fullWidth
                                    placeholder="/pricing"
                                    maxLength={SURVEY_NAME_MAX_LENGTH}
                                    value={quickForm.urlMatch}
                                    onChange={(v) => setFormField('urlMatch', v)}
                                />
                                <LemonSelect
                                    size="small"
                                    options={URL_MATCH_TYPE_OPTIONS}
                                    value={quickForm.urlMatchType}
                                    onChange={(v) => setFormField('urlMatchType', v)}
                                />
                            </div>
                            <span className="text-xs text-muted block">
                                Auto-filled from current page. Pick a match type — exact targets only this URL, contains
                                matches any URL containing the value.
                            </span>
                        </div>
                    )}
                </div>
            </div>
        </section>
    )
}

function WhenSection(): JSX.Element {
    const { quickForm } = useValues(surveysToolbarLogic)
    const { setFormField } = useActions(surveysToolbarLogic)

    return (
        <section>
            <h3 className="text-xs font-semibold text-muted-3000 uppercase tracking-wide mb-3">When</h3>
            <div className="space-y-3">
                <div>
                    <LemonRadio
                        value={quickForm.triggerMode}
                        onChange={(v) => setFormField('triggerMode', v)}
                        options={[
                            {
                                value: 'pageview',
                                label: 'On page load',
                                description: 'Shows when the user visits the page',
                            },
                            {
                                value: 'event',
                                label: 'When an event is captured',
                                description: 'Trigger the survey after a specific event',
                            },
                        ]}
                    />
                    {quickForm.triggerMode === 'event' && (
                        <div className="mt-2 ml-6">
                            <LemonInput
                                size="small"
                                fullWidth
                                placeholder="e.g. purchase_completed"
                                maxLength={SURVEY_NAME_MAX_LENGTH}
                                value={quickForm.triggerEventName}
                                onChange={(v) => setFormField('triggerEventName', v)}
                            />
                            <span className="text-xs text-muted mt-0.5 block">
                                Enter the event name that triggers this survey
                            </span>
                        </div>
                    )}
                </div>

                <div>
                    <p className="text-xs text-muted mb-2">How often can someone see this?</p>
                    <LemonSegmentedButton
                        value={quickForm.frequency}
                        onChange={(v) => setFormField('frequency', v)}
                        options={FREQUENCY_OPTIONS.map((opt) => ({
                            value: opt.value,
                            label: opt.label,
                        }))}
                        fullWidth
                        size="small"
                    />
                </div>

                <div>
                    <p className="text-xs font-medium text-muted mb-1">Delay before showing</p>
                    <div className="flex items-center gap-2">
                        <LemonInput
                            type="number"
                            min={0}
                            max={SURVEY_DELAY_MAX_SECONDS}
                            size="small"
                            value={quickForm.delaySeconds}
                            onChange={(val) => setFormField('delaySeconds', clampDelaySeconds(val))}
                            className="w-20"
                        />
                        <span className="text-xs text-muted">seconds after conditions are met</span>
                    </div>
                </div>
            </div>
        </section>
    )
}

function statusLabel(status: 'draft' | 'active' | 'complete' | null): string {
    if (status === 'active') {
        return 'Live on your site'
    }
    if (status === 'draft') {
        return 'Draft'
    }
    if (status === 'complete') {
        return 'Ended'
    }
    return ''
}

function statusClass(status: 'draft' | 'active' | 'complete' | null): string {
    if (status === 'active') {
        return 'text-success-3000'
    }
    if (status === 'draft') {
        return 'text-warning-3000'
    }
    return 'text-muted'
}

export function SurveySidebar(): JSX.Element | null {
    const { isCreating, isSubmitting, isLifecyclePending, canProceed, canProceedReason, editingSurvey } =
        useValues(surveysToolbarLogic)
    const { cancelQuickCreate, submitQuickCreate, stopSurvey, resumeSurvey, archiveSurvey } =
        useActions(surveysToolbarLogic)
    const { uiHost } = useValues(toolbarConfigLogic)
    const isEditing = !!editingSurvey
    const status = editingSurvey ? getSurveyStatus(editingSurvey) : null
    const disabledReason = canProceed ? undefined : (canProceedReason ?? 'Add a survey name and question')
    const anyPending = isSubmitting || isLifecyclePending

    // Snapshot host body styles before mutating, restore on cleanup. Naive
    // cleanup to '' would clobber any inline styles the host already had.
    useEffect(() => {
        if (!isCreating) {
            return
        }
        const prevMargin = document.body.style.marginRight
        const prevTransition = document.body.style.transition
        document.body.style.transition = `margin ${SIDEBAR_TRANSITION_MS}ms ease-out`
        document.body.style.marginRight = `${SIDEBAR_WIDTH}px`
        return () => {
            document.body.style.marginRight = prevMargin
            document.body.style.transition = prevTransition
        }
    }, [isCreating])

    if (!isCreating) {
        return null
    }

    const handleEnd = (): void => {
        if (!editingSurvey) {
            return
        }
        if (window.confirm('End this survey now? It will stop showing to new users.')) {
            stopSurvey(editingSurvey)
        }
    }

    const handleResume = (): void => {
        if (!editingSurvey) {
            return
        }
        resumeSurvey(editingSurvey)
    }

    const handleArchive = (): void => {
        if (!editingSurvey) {
            return
        }
        if (
            window.confirm(
                'Archive this survey? It will be hidden from the toolbar list. You can restore it from the PostHog surveys page.'
            )
        ) {
            archiveSurvey(editingSurvey)
        }
    }

    return (
        <>
            <SurveyLivePreview />
            <div
                className="flex flex-col"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    position: 'fixed',
                    top: 0,
                    right: 0,
                    bottom: 0,
                    width: SIDEBAR_WIDTH,
                    backgroundColor: 'var(--color-bg-3000)',
                    borderLeft: '1px solid var(--border-bold-3000)',
                    boxShadow: '-4px 0 24px rgba(0, 0, 0, 0.4)',
                    zIndex: SIDEBAR_Z_INDEX,
                    pointerEvents: 'auto',
                    color: 'var(--text-3000)',
                }}
            >
                {/* Header */}
                <div className="px-4 pt-4 pb-3 border-b border-border-bold-3000 bg-bg-light">
                    {/* Title row */}
                    <div className="flex items-start justify-between gap-2 mb-3">
                        <div className="min-w-0 flex-1">
                            <h2 className="m-0 text-sm font-semibold leading-tight truncate">
                                {isEditing ? 'Edit survey' : 'New survey'}
                            </h2>
                            {isEditing && status && (
                                <p className={`text-xs font-medium m-0 mt-0.5 ${statusClass(status)}`}>
                                    {statusLabel(status)}
                                </p>
                            )}
                        </div>
                        <div className="flex items-center gap-1 shrink-0">
                            {isEditing && editingSurvey && (
                                <LemonMenu
                                    placement="bottom-end"
                                    items={[
                                        {
                                            label: 'Archive survey',
                                            icon: <IconArchive />,
                                            status: 'danger',
                                            onClick: handleArchive,
                                            disabledReason: anyPending ? 'Action in progress' : undefined,
                                        },
                                    ]}
                                >
                                    <LemonButton
                                        size="xsmall"
                                        type="tertiary"
                                        icon={<IconEllipsis />}
                                        tooltip="More actions"
                                    />
                                </LemonMenu>
                            )}
                            <button
                                type="button"
                                onClick={cancelQuickCreate}
                                aria-label="Close"
                                disabled={isSubmitting}
                                className="p-1 rounded border-none bg-transparent cursor-pointer text-muted-3000 hover:text-text-3000 flex items-center justify-center disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                                <IconX className="w-4 h-4" />
                            </button>
                        </div>
                    </div>

                    {/* Primary action row — pairs save with the most relevant lifecycle action */}
                    {isEditing && editingSurvey ? (
                        <div className="flex gap-2">
                            {status === 'draft' && (
                                <>
                                    <LemonButton
                                        type="tertiary"
                                        center
                                        className="flex-1"
                                        loading={isSubmitting}
                                        disabledReason={disabledReason}
                                        onClick={() => submitQuickCreate(false)}
                                    >
                                        Save changes
                                    </LemonButton>
                                    <LemonButton
                                        type="primary"
                                        center
                                        className="flex-1"
                                        icon={<IconRocket />}
                                        loading={isSubmitting}
                                        disabledReason={disabledReason}
                                        onClick={() => submitQuickCreate(true)}
                                    >
                                        Launch
                                    </LemonButton>
                                </>
                            )}
                            {status === 'active' && (
                                <>
                                    <LemonButton
                                        type="tertiary"
                                        center
                                        className="flex-1"
                                        loading={isLifecyclePending}
                                        disabledReason={anyPending ? 'Action in progress' : undefined}
                                        onClick={handleEnd}
                                    >
                                        End survey
                                    </LemonButton>
                                    <LemonButton
                                        type="primary"
                                        center
                                        className="flex-1"
                                        loading={isSubmitting}
                                        disabledReason={disabledReason}
                                        onClick={() => submitQuickCreate(false)}
                                    >
                                        Save changes
                                    </LemonButton>
                                </>
                            )}
                            {status === 'complete' && (
                                <>
                                    <LemonButton
                                        type="tertiary"
                                        center
                                        className="flex-1"
                                        loading={isLifecyclePending}
                                        disabledReason={anyPending ? 'Action in progress' : undefined}
                                        onClick={handleResume}
                                    >
                                        Resume
                                    </LemonButton>
                                    <LemonButton
                                        type="primary"
                                        center
                                        className="flex-1"
                                        loading={isSubmitting}
                                        disabledReason={disabledReason}
                                        onClick={() => submitQuickCreate(false)}
                                    >
                                        Save changes
                                    </LemonButton>
                                </>
                            )}
                        </div>
                    ) : (
                        <div className="flex gap-2">
                            <LemonButton
                                type="tertiary"
                                center
                                className="flex-1"
                                loading={isSubmitting}
                                disabledReason={disabledReason}
                                onClick={() => submitQuickCreate(false)}
                            >
                                Save draft
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                center
                                className="flex-1"
                                icon={<IconRocket />}
                                loading={isSubmitting}
                                disabledReason={disabledReason}
                                onClick={() => submitQuickCreate(true)}
                            >
                                Launch
                            </LemonButton>
                        </div>
                    )}
                </div>

                {/* Scrollable form body */}
                <div className="flex-1 overflow-y-auto p-4 space-y-5">
                    {/* Compact info strip */}
                    <p className="text-xs text-muted m-0 leading-snug">
                        Quick editor for single-question surveys. Need branching or multiple questions?{' '}
                        <Link to={joinWithUiHost(uiHost, urls.surveys())} target="_blank" subtle>
                            Open in PostHog <IconExternal className="inline w-3 h-3" />
                        </Link>
                    </p>
                    <QuestionSection />
                    <div className="border-t border-border-bold-3000" />
                    <WhereSection />
                    <div className="border-t border-border-bold-3000" />
                    <WhenSection />
                </div>
            </div>
        </>
    )
}
