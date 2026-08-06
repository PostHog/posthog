import '../../../public/surveys/hosted-survey.css'

import { DndContext, DragEndEvent } from '@dnd-kit/core'
import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useMemo, useState } from 'react'

import { IconChevronDown, IconExternal, IconGitBranch, IconTrash, IconWarning } from '@posthog/icons'
import {
    LemonButton,
    LemonCheckbox,
    LemonCollapse,
    LemonDialog,
    LemonDropdown,
    LemonInput,
    LemonSwitch,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { SortableDragIcon } from 'lib/lemon-ui/icons'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { Customization } from 'scenes/surveys/survey-appearance/SurveyCustomization'
import { SurveyTranslationFields } from 'scenes/surveys/SurveyTranslationFields'
import { SurveyTranslations } from 'scenes/surveys/SurveyTranslations'
import { getSurveyWithTranslatedContent } from 'scenes/surveys/surveyTranslationUtils'
import { sanitizeSurveyAppearance, validateSurveyAppearance } from 'scenes/surveys/utils'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { Survey, SurveyQuestion, SurveyQuestionType, SurveyType } from '~/types'

import { SurveyBranchingFlowModal } from './branching-flow/SurveyBranchingFlowModal'
import { defaultSurveyFieldValues, NewSurvey, SurveyQuestionLabel } from './constants'
import { CopySurveyLink } from './CopySurveyLink'
import { HostedSurveyCanvas } from './hosted-canvas/HostedSurveyCanvas'
import { HostedSurveySettingsPanel } from './hosted-canvas/HostedSurveySettingsPanel'
import { surveyLogic } from './surveyLogic'
import { SurveyResponsesCollection } from './SurveyResponsesCollection'
import { AddQuestionButton } from './wizard/AddQuestionButton'

function getHostedSurveyUrl(surveyId: string): string {
    const url = new URL(window.location.origin)
    url.pathname = `/external_surveys/${surveyId}`
    return url.toString()
}

function moveQuestion(questions: SurveyQuestion[], from: number, to: number): SurveyQuestion[] {
    const nextQuestions = [...questions]
    const [question] = nextQuestions.splice(from, 1)
    nextQuestions.splice(to, 0, question)
    return nextQuestions.map((q) => ({ ...q }))
}

function HostedSurveyQuestionRail({
    id,
    survey,
    hostedSurveyUrl,
    selectedPageIndex,
    onSelectPage,
    onAddQuestion,
    onAddConfirmation,
    onMoveQuestion,
    onDeleteQuestion,
    onIframeEmbeddingChange,
}: {
    id: string
    survey: Survey | NewSurvey
    hostedSurveyUrl: string | null
    selectedPageIndex: number
    onSelectPage: (pageIndex: number) => void
    onAddQuestion: (type: SurveyQuestionType) => void
    onAddConfirmation: () => void
    onMoveQuestion: (from: number, to: number) => void
    onDeleteQuestion: (index: number) => void
    onIframeEmbeddingChange: (checked: boolean) => void
}): JSX.Element {
    const sortedItemIds = survey.questions.map((_, index) => index.toString())

    const handleDragEnd = ({ active, over }: DragEndEvent): void => {
        if (!over || active.id === over.id) {
            return
        }

        const oldIndex = sortedItemIds.indexOf(active.id.toString())
        const newIndex = sortedItemIds.indexOf(over.id.toString())
        if (oldIndex < 0 || newIndex < 0) {
            return
        }

        onMoveQuestion(oldIndex, newIndex)
    }

    return (
        <nav className="flex min-w-0 flex-col gap-3 rounded border bg-surface-primary p-3">
            <div className="flex items-center justify-between gap-2 border-b pb-2">
                <div>
                    <h3 className="mb-0 text-sm font-semibold uppercase tracking-wide text-secondary">Flow</h3>
                    <p className="mb-0 text-xs text-muted">{survey.questions.length} question steps</p>
                </div>
            </div>
            <div className="flex flex-col gap-2">
                <DndContext onDragEnd={handleDragEnd}>
                    <SortableContext
                        disabled={survey.questions.length <= 1}
                        items={sortedItemIds}
                        strategy={verticalListSortingStrategy}
                    >
                        <div className="flex flex-col gap-1">
                            {survey.questions.map((question, index) => (
                                <HostedSurveyQuestionRailItem
                                    key={`${question.id ?? 'question'}-${index}`}
                                    id={index.toString()}
                                    question={question}
                                    index={index}
                                    isSelected={selectedPageIndex === index}
                                    canReorder={survey.questions.length > 1}
                                    canDelete={survey.questions.length > 1}
                                    onSelect={() => onSelectPage(index)}
                                    onDelete={() => onDeleteQuestion(index)}
                                />
                            ))}
                        </div>
                    </SortableContext>
                </DndContext>
                {survey.appearance?.displayThankYouMessage ? (
                    <button
                        type="button"
                        className={`min-h-11 rounded border px-3 py-2 text-left text-sm transition-colors ${
                            selectedPageIndex === survey.questions.length
                                ? 'border-primary bg-primary-highlight text-primary'
                                : 'bg-bg-light hover:bg-fill-highlight-50'
                        }`}
                        onClick={() => onSelectPage(survey.questions.length)}
                    >
                        <span className="block font-medium">Confirmation</span>
                        <span className="block text-xs text-secondary">End screen</span>
                    </button>
                ) : (
                    <LemonButton type="secondary" size="small" onClick={onAddConfirmation} className="mt-1" fullWidth>
                        Add confirmation
                    </LemonButton>
                )}
                <AddQuestionButton onAdd={onAddQuestion} />
            </div>
            <HostedSurveySharingPanel
                id={id}
                hostedSurveyUrl={hostedSurveyUrl}
                enableIframeEmbedding={!!survey.enable_iframe_embedding}
                onIframeEmbeddingChange={onIframeEmbeddingChange}
            />
        </nav>
    )
}

function HostedSurveyQuestionRailItem({
    id,
    question,
    index,
    isSelected,
    canReorder,
    canDelete,
    onSelect,
    onDelete,
}: {
    id: string
    question: SurveyQuestion
    index: number
    isSelected: boolean
    canReorder: boolean
    canDelete: boolean
    onSelect: () => void
    onDelete: () => void
}): JSX.Element {
    const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
        id,
        animateLayoutChanges: () => false,
    })

    return (
        <div
            ref={setNodeRef}
            {...attributes}
            className={`group flex min-h-[3.75rem] items-center gap-2 rounded border px-2 py-2 transition-colors ${
                isSelected
                    ? 'border-primary bg-primary-highlight text-primary'
                    : 'bg-bg-light hover:bg-fill-highlight-50'
            } ${isDragging ? 'opacity-50' : ''}`}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                transform: CSS.Translate.toString(transform),
                transition,
            }}
        >
            {canReorder ? (
                <span
                    className="shrink-0 cursor-grab text-muted hover:text-primary active:cursor-grabbing"
                    {...listeners}
                    aria-label={`Reorder question ${index + 1}`}
                >
                    <SortableDragIcon />
                </span>
            ) : null}
            <button type="button" className="flex min-w-0 flex-1 flex-col text-left" onClick={onSelect}>
                <span className="min-w-0 truncate text-sm font-medium">{question.question || 'Untitled question'}</span>
                <span className="mt-0.5 flex items-center gap-1 text-xs text-secondary">
                    <span>{index + 1}</span>
                    <span aria-hidden="true">/</span>
                    <span>{SurveyQuestionLabel[question.type]}</span>
                </span>
            </button>
            {canDelete ? (
                <LemonButton
                    icon={<IconTrash />}
                    size="xsmall"
                    status="danger"
                    onClick={onDelete}
                    aria-label="Delete question"
                />
            ) : null}
        </div>
    )
}

function HostedSurveySharingPanel({
    id,
    hostedSurveyUrl,
    enableIframeEmbedding,
    onIframeEmbeddingChange,
}: {
    id: string
    hostedSurveyUrl: string | null
    enableIframeEmbedding: boolean
    onIframeEmbeddingChange: (checked: boolean) => void
}): JSX.Element {
    return (
        <section className="mt-1 border-t pt-3">
            <div className="mb-2">
                <h3 className="mb-0 text-sm font-semibold uppercase tracking-wide text-secondary">Sharing</h3>
                <p className="mb-0 text-xs text-muted">URL options for hosted surveys</p>
            </div>
            <div className="flex flex-col gap-2">
                {hostedSurveyUrl ? (
                    <CopySurveyLink
                        surveyId={id}
                        enableIframeEmbedding={enableIframeEmbedding}
                        className="flex-wrap [&_.LemonButton]:flex-1 [&_.LemonButton]:justify-center"
                    />
                ) : (
                    <div className="rounded border bg-bg-light p-2 text-xs text-secondary">
                        Save this survey before copying a public URL or embed code.
                    </div>
                )}
                <Tooltip title="Enable this to embed the survey in tools like Framer, Webflow, or other website builders that use iframes.">
                    <div className="flex min-h-10 items-center">
                        <LemonSwitch
                            checked={enableIframeEmbedding}
                            onChange={onIframeEmbeddingChange}
                            label="Allow iframe embedding"
                        />
                    </div>
                </Tooltip>
                <div className="flex items-center justify-between gap-2 py-1 text-xs text-secondary">
                    <span className="min-w-0">Identify, prefill, and translate with URL parameters.</span>
                    <HostedSurveyUrlParamsDropdown />
                </div>
            </div>
        </section>
    )
}

function HostedSurveyUrlParamsDropdown(): JSX.Element {
    return (
        <LemonDropdown
            placement="bottom-start"
            overlay={
                <div className="max-w-80 p-3 text-xs text-secondary">
                    <p className="mb-2 font-semibold text-default">Useful URL params</p>
                    <dl className="mb-0 flex flex-col gap-2">
                        <div>
                            <dt className="font-medium text-default">
                                <code className="rounded bg-surface-tertiary px-1">distinct_id</code>
                            </dt>
                            <dd className="mb-0">Identify the respondent.</dd>
                        </div>
                        <div>
                            <dt className="font-medium text-default">
                                <code className="rounded bg-surface-tertiary px-1">q1</code>,{' '}
                                <code className="rounded bg-surface-tertiary px-1">q2</code>
                            </dt>
                            <dd className="mb-0">Prefill answers by question order. Complete prefills auto-submit.</dd>
                        </div>
                        <div>
                            <dt className="font-medium text-default">
                                <code className="rounded bg-surface-tertiary px-1">display_language</code>
                            </dt>
                            <dd className="mb-0">Force a translated survey language.</dd>
                        </div>
                        <div>
                            <dt className="font-medium text-default">Custom params</dt>
                            <dd className="mb-0">Extra params are captured as survey response event properties.</dd>
                        </div>
                    </dl>
                    <Link
                        to="https://posthog.com/docs/surveys/creating-surveys#identifying-respondents-on-hosted-surveys"
                        target="_blank"
                        className="mt-2 inline-block"
                    >
                        Hosted survey docs
                    </Link>
                </div>
            }
        >
            <LemonButton type="tertiary" size="xsmall" sideIcon={<IconChevronDown />}>
                URL params
            </LemonButton>
        </LemonDropdown>
    )
}

function HostedSurveyEditorHeader({
    id,
    survey,
    surveyLoading,
    hostedSurveyUrl,
    onNameChange,
    onDescriptionChange,
    onCancel,
    onConvertToInApp,
}: {
    id: string
    survey: Survey | NewSurvey
    surveyLoading: boolean
    hostedSurveyUrl: string | null
    onNameChange: (name: string) => void
    onDescriptionChange: (description: string) => void
    onCancel: () => void
    onConvertToInApp: () => void
}): JSX.Element {
    return (
        <header className="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
            <div className="grid min-w-0 flex-1 gap-3 lg:grid-cols-[minmax(260px,0.55fr)_minmax(220px,0.45fr)]">
                <LemonField.Pure label="Survey name" htmlFor="hosted-survey-name">
                    <LemonInput
                        id="hosted-survey-name"
                        value={survey.name}
                        onChange={onNameChange}
                        placeholder="Untitled hosted survey"
                        className="font-semibold"
                    />
                </LemonField.Pure>
                <LemonField.Pure
                    label="Internal description"
                    info="Not shown to respondents. Helps your team find this survey later."
                    htmlFor="hosted-survey-description"
                >
                    <LemonInput
                        id="hosted-survey-description"
                        value={survey.description ?? ''}
                        onChange={onDescriptionChange}
                        placeholder="What this survey is for"
                    />
                </LemonField.Pure>
            </div>
            <div className="flex shrink-0 flex-wrap items-center gap-2">
                <LemonButton type="secondary" size="small" onClick={onConvertToInApp}>
                    Convert to in-app
                </LemonButton>
                {hostedSurveyUrl ? (
                    <LemonButton type="secondary" size="small" icon={<IconExternal />} to={hostedSurveyUrl} targetBlank>
                        Open
                    </LemonButton>
                ) : null}
                <LemonButton
                    data-attr="cancel-survey"
                    type="secondary"
                    loading={surveyLoading}
                    onClick={onCancel}
                    size="small"
                >
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    data-attr="save-survey"
                    htmlType="submit"
                    loading={surveyLoading}
                    form="survey"
                    size="small"
                >
                    {id === 'new' ? 'Save as draft' : 'Save'}
                </LemonButton>
            </div>
        </header>
    )
}

export function HostedSurveyEdit({ id }: { id: string }): JSX.Element {
    const { survey, selectedPageIndex, hasBranchingLogic, surveyErrors, surveyLoading, editingLanguage } =
        useValues(surveyLogic)
    const {
        deleteBranchingLogic,
        editingSurvey,
        loadSurvey,
        setSelectedPageIndex,
        setSurveyManualErrors,
        setSurveyValue,
    } = useActions(surveyLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const [showFlowModal, setShowFlowModal] = useState(false)
    const [viewport, setViewport] = useState<'desktop' | 'mobile'>('desktop')

    const surveyTranslationsEnabled = !!featureFlags[FEATURE_FLAGS.SURVEYS_TRANSLATIONS]
    const activeLanguage = surveyTranslationsEnabled ? editingLanguage : null
    // Translation-aware view of the survey for the canvas to render. Edits made
    // on the canvas still flow through surveyLogic against the raw survey, so
    // text edits while a translation is being edited won't write to the
    // wrong field — but they also won't update translations. Use the
    // Translations section below the canvas for that.
    const previewSurvey = useMemo(
        () => getSurveyWithTranslatedContent(survey, activeLanguage),
        [survey, activeLanguage]
    )
    const maxPageIndex = Math.max(survey.questions.length + (survey.appearance?.displayThankYouMessage ? 1 : 0) - 1, 0)
    const activePageIndex = Math.min(selectedPageIndex ?? 0, maxPageIndex)
    const isConfirmationSelected =
        !!survey.appearance?.displayThankYouMessage && activePageIndex === survey.questions.length
    const hostedSurveyUrl = id === 'new' ? null : getHostedSurveyUrl(id)

    const removeConfirmationScreen = (): void => {
        setSurveyValue('appearance', {
            ...survey.appearance,
            displayThankYouMessage: false,
        })
        setSelectedPageIndex(Math.max(survey.questions.length - 1, 0))
    }

    const runAfterBranchingConfirmation = (action: () => void, description: JSX.Element): void => {
        if (!hasBranchingLogic) {
            action()
            return
        }

        LemonDialog.open({
            title: 'Your survey has active branching logic',
            description,
            primaryButton: {
                children: 'Continue',
                status: 'danger',
                onClick: () => {
                    deleteBranchingLogic()
                    action()
                },
            },
            secondaryButton: {
                children: 'Cancel',
            },
        })
    }

    const addQuestion = (type: SurveyQuestionType): void => {
        const newQuestion = { ...defaultSurveyFieldValues[type].questions[0] } as SurveyQuestion
        const existingLanguages = Object.keys(survey.translations || {})

        if (existingLanguages.length > 0) {
            newQuestion.translations = {}
            existingLanguages.forEach((language) => {
                newQuestion.translations = {
                    ...newQuestion.translations,
                    [language]: {
                        question: newQuestion.question || '',
                        description: newQuestion.description || '',
                        buttonText: newQuestion.buttonText || '',
                    },
                }
            })
        }

        setSurveyValue('questions', [...survey.questions, newQuestion])
        setSelectedPageIndex(survey.questions.length)
    }

    const moveSurveyQuestion = (from: number, to: number): void => {
        runAfterBranchingConfirmation(
            () => {
                setSurveyValue('questions', moveQuestion(survey.questions, from, to))
                setSelectedPageIndex(to)
            },
            <p className="py-2">Rearranging questions will remove your branching logic. Continue?</p>
        )
    }

    const deleteSurveyQuestion = (index: number): void => {
        runAfterBranchingConfirmation(
            () => {
                setSurveyValue(
                    'questions',
                    survey.questions.filter((_, questionIndex) => questionIndex !== index)
                )
                setSelectedPageIndex(Math.max(index - 1, 0))
            },
            <p className="py-2">Deleting this question will remove your branching logic. Continue?</p>
        )
    }

    const handleCancelClick = (): void => {
        editingSurvey(false)
        if (id === 'new') {
            router.actions.push(urls.surveys())
        } else {
            loadSurvey()
        }
    }

    const convertToInAppSurvey = (): void => {
        LemonDialog.open({
            title: 'Convert to in-app survey?',
            description: (
                <p className="py-2">
                    This keeps the questions and style, then switches the editor back to the in-app survey setup where
                    display conditions and placement are available.
                </p>
            ),
            primaryButton: {
                children: 'Convert',
                onClick: () => {
                    setSurveyValue('type', SurveyType.Popover)
                    setSurveyValue('enable_iframe_embedding', false)
                    setSelectedPageIndex(0)
                },
            },
            secondaryButton: {
                children: 'Cancel',
            },
        })
    }

    return (
        <SceneContent>
            <div className="flex flex-col gap-4">
                <HostedSurveyEditorHeader
                    id={id}
                    survey={survey}
                    surveyLoading={surveyLoading}
                    hostedSurveyUrl={hostedSurveyUrl}
                    onNameChange={(name) => setSurveyValue('name', name)}
                    onDescriptionChange={(description) => setSurveyValue('description', description)}
                    onCancel={handleCancelClick}
                    onConvertToInApp={convertToInAppSurvey}
                />
                <div className="grid min-h-[640px] grid-cols-1 gap-4 xl:grid-cols-[300px_minmax(0,1fr)]">
                    <HostedSurveyQuestionRail
                        id={id}
                        survey={survey}
                        hostedSurveyUrl={hostedSurveyUrl}
                        selectedPageIndex={activePageIndex}
                        onSelectPage={setSelectedPageIndex}
                        onAddQuestion={addQuestion}
                        onAddConfirmation={() => {
                            setSurveyValue('appearance', {
                                ...survey.appearance,
                                displayThankYouMessage: true,
                            })
                            setSelectedPageIndex(survey.questions.length)
                        }}
                        onMoveQuestion={moveSurveyQuestion}
                        onDeleteQuestion={deleteSurveyQuestion}
                        onIframeEmbeddingChange={(checked) => setSurveyValue('enable_iframe_embedding', checked)}
                    />
                    <div className="HostedSurveyCanvasLayout">
                        <HostedSurveyCanvas
                            survey={previewSurvey}
                            activePageIndex={activePageIndex}
                            isConfirmation={isConfirmationSelected}
                            viewport={viewport}
                        />
                        <HostedSurveySettingsPanel
                            activePageIndex={activePageIndex}
                            isConfirmation={isConfirmationSelected}
                            viewport={viewport}
                            onViewportChange={setViewport}
                            onRemoveConfirmation={removeConfirmationScreen}
                        />
                    </div>
                </div>

                {surveyTranslationsEnabled ? (
                    <section className="rounded border bg-surface-primary p-5">
                        <div className="mb-4 border-b pb-3">
                            <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-secondary">
                                Languages
                            </p>
                            <h2 className="mb-0 text-base font-semibold">Translations</h2>
                            <p className="mb-0 text-xs text-secondary">
                                Localize the hosted survey without changing its structure.
                            </p>
                        </div>
                        <div className="flex flex-col gap-3">
                            {editingLanguage ? (
                                <div className="rounded border border-warning bg-warning-highlight p-3 text-sm">
                                    Editing translated survey content. Question order and settings stay in the original
                                    language.
                                </div>
                            ) : null}
                            <SurveyTranslations />
                            {activeLanguage ? <SurveyTranslationFields activeLanguage={activeLanguage} /> : null}
                        </div>
                    </section>
                ) : null}

                <LemonCollapse
                    className="bg-surface-primary rounded border"
                    panels={[
                        {
                            key: 'appearance',
                            header: 'Style',
                            content: (
                                <LemonField name="appearance" label="">
                                    {({ onChange }) => (
                                        <Customization
                                            survey={survey}
                                            hasBranchingLogic={hasBranchingLogic}
                                            deleteBranchingLogic={deleteBranchingLogic}
                                            onTranslationsChange={(translations) =>
                                                setSurveyValue('translations', translations)
                                            }
                                            hasRatingButtons={survey.questions.some(
                                                (question) => question.type === SurveyQuestionType.Rating
                                            )}
                                            hasPlaceholderText={survey.questions.some(
                                                (question) => question.type === SurveyQuestionType.Open
                                            )}
                                            onAppearanceChange={(appearance) => {
                                                const newAppearance = sanitizeSurveyAppearance({
                                                    ...survey.appearance,
                                                    ...appearance,
                                                })
                                                onChange(newAppearance)
                                                if (newAppearance) {
                                                    setSurveyManualErrors(
                                                        validateSurveyAppearance(
                                                            newAppearance,
                                                            true,
                                                            SurveyType.ExternalSurvey
                                                        )
                                                    )
                                                }
                                            }}
                                            validationErrors={surveyErrors?.appearance}
                                        />
                                    )}
                                </LemonField>
                            ),
                        },
                        {
                            key: 'collection',
                            header: 'Collection',
                            content: (
                                <div className="flex flex-col gap-4">
                                    <LemonField.Pure label={<h3 className="mb-0">Completion limit</h3>}>
                                        <div className="flex flex-wrap items-center gap-2">
                                            <LemonCheckbox
                                                checked={!!survey.responses_limit}
                                                onChange={(checked) =>
                                                    setSurveyValue('responses_limit', checked ? 100 : null)
                                                }
                                                label="Stop collecting after"
                                            />
                                            <LemonInput
                                                type="number"
                                                min={1}
                                                size="small"
                                                value={survey.responses_limit || NaN}
                                                onChange={(value) => {
                                                    setSurveyValue('responses_limit', value && value > 0 ? value : null)
                                                }}
                                                className="w-20"
                                            />
                                            responses
                                        </div>
                                    </LemonField.Pure>
                                    <SurveyResponsesCollection />
                                </div>
                            ),
                        },
                    ]}
                />

                {hasBranchingLogic ? (
                    <LemonButton
                        data-attr="preview-survey-branching"
                        type="secondary"
                        className="w-max"
                        icon={<IconGitBranch />}
                        onClick={() => setShowFlowModal(true)}
                    >
                        Preview branching flow
                    </LemonButton>
                ) : null}

                {id === 'new' ? (
                    <div className="flex items-center gap-2 rounded border bg-accent-highlight p-3 text-sm">
                        <IconWarning className="text-warning" />
                        Save this hosted survey before sharing or embedding it.
                    </div>
                ) : null}
            </div>
            <SurveyBranchingFlowModal survey={survey} isOpen={showFlowModal} onClose={() => setShowFlowModal(false)} />
        </SceneContent>
    )
}
