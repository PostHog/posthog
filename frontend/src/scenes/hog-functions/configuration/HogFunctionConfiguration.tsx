import { IconCheck, IconInfo, IconPlus, IconX } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDivider,
    LemonDropdown,
    LemonInput,
    LemonSwitch,
    LemonTag,
    LemonTextArea,
    Link,
    SpinnerOverlay,
} from '@posthog/lemon-ui'
import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { CyclotronJobInputs } from 'lib/components/CyclotronJob/CyclotronJobInputs'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { PayGateButton } from 'lib/components/PayGateMini/PayGateButton'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'
import { useRef } from 'react'
import { hogFunctionConfigurationLogic } from 'scenes/hog-functions/configuration/hogFunctionConfigurationLogic'
import { HogFunctionFilters } from 'scenes/hog-functions/filters/HogFunctionFilters'
import { HogFunctionMappings } from 'scenes/hog-functions/mapping/HogFunctionMappings'
import { HogFunctionEventEstimates } from 'scenes/hog-functions/metrics/HogFunctionEventEstimates'
import MaxTool from 'scenes/max/MaxTool'

import { AvailableFeature, CyclotronJobInputSchemaType } from '~/types'

import { HogFunctionStatusIndicator } from '../misc/HogFunctionStatusIndicator'
import { HogFunctionStatusTag } from '../misc/HogFunctionStatusTag'
import { HogFunctionSourceWebhookInfo } from './components/HogFunctionSourceWebhookInfo'
import { HogFunctionSourceWebhookTest } from './components/HogFunctionSourceWebhookTest'
import { HogFunctionIconEditable } from './HogFunctionIcon'
import { HogFunctionTest } from './HogFunctionTest'

export interface HogFunctionConfigurationProps {
    templateId?: string | null
    id?: string | null
    logicKey?: string
}

export function HogFunctionConfiguration({ templateId, id, logicKey }: HogFunctionConfigurationProps): JSX.Element {
    const logicProps = { templateId, id, logicKey }
    const logic = hogFunctionConfigurationLogic(logicProps)
    const {
        isConfigurationSubmitting,
        configurationChanged,
        showSource,
        configuration,
        loading,
        loaded,
        hogFunction,
        willReEnableOnSave,
        willChangeEnabledOnSave,
        sampleGlobalsWithInputs,
        showPaygate,
        hasAddon,
        template,
        templateHasChanged,
        type,
        usesGroups,
        hasGroupsAddon,
        mightDropEvents,
        oldHogCode,
        newHogCode,
        oldInputs,
        newInputs,
        sourceUsesEvents,
    } = useValues(logic)

    const {
        submitConfiguration,
        resetForm,
        setShowSource,
        duplicate,
        resetToTemplate,
        duplicateFromTemplate,
        setConfigurationValue,
        deleteHogFunction,
        setOldHogCode,
        setNewHogCode,
        clearHogCodeDiff,
        reportAIHogFunctionPrompted,
        reportAIHogFunctionAccepted,
        reportAIHogFunctionRejected,
        reportAIHogFunctionPromptOpen,
        setOldInputs,
        setNewInputs,
        clearInputsDiff,
        reportAIHogFunctionInputsPrompted,
        reportAIHogFunctionInputsAccepted,
        reportAIHogFunctionInputsRejected,
        reportAIHogFunctionInputsPromptOpen,
    } = useActions(logic)
    const canEditTransformationHogCode = useFeatureFlag('HOG_TRANSFORMATIONS_CUSTOM_HOG_ENABLED')
    const aiHogFunctionCreation = !!useFeatureFlag('AI_HOG_FUNCTION_CREATION')
    const sourceCodeRef = useRef<HTMLDivElement>(null)

    if (loading && !loaded) {
        return <SpinnerOverlay />
    }

    if (!loaded) {
        return <NotFound object="Hog function" />
    }

    const isLegacyPlugin = (template?.id || hogFunction?.template?.id)?.startsWith('plugin-')

    const headerButtons = (
        <>
            {!templateId && (
                <>
                    <More
                        overlay={
                            <>
                                {!isLegacyPlugin && (
                                    <LemonButton fullWidth onClick={() => duplicate()}>
                                        Duplicate
                                    </LemonButton>
                                )}
                                <LemonDivider />
                                <LemonButton status="danger" fullWidth onClick={() => deleteHogFunction()}>
                                    Delete
                                </LemonButton>
                            </>
                        }
                    />
                    <LemonDivider vertical />
                </>
            )}
        </>
    )

    const saveButtons = (
        <>
            {configurationChanged ? (
                <LemonButton
                    type="secondary"
                    htmlType="reset"
                    onClick={() => resetForm()}
                    disabledReason={
                        !configurationChanged
                            ? 'No changes'
                            : isConfigurationSubmitting
                            ? 'Saving in progress…'
                            : undefined
                    }
                >
                    Clear changes
                </LemonButton>
            ) : null}
            <LemonButton
                type="primary"
                htmlType="submit"
                onClick={submitConfiguration}
                loading={isConfigurationSubmitting}
            >
                {templateId ? 'Create' : 'Save'}
                {willReEnableOnSave
                    ? ' & re-enable'
                    : willChangeEnabledOnSave
                    ? ` & ${configuration.enabled ? 'enable' : 'disable'}`
                    : ''}
            </LemonButton>
        </>
    )

    if (showPaygate) {
        return <PayGateMini feature={AvailableFeature.DATA_PIPELINES} />
    }

    const showFilters = ['destination', 'internal_destination', 'site_destination', 'transformation'].includes(type)
    const showExpectedVolume = sourceUsesEvents && ['destination', 'site_destination', 'transformation'].includes(type)
    const canEditSource =
        ['site_destination', 'site_app', 'source_webhook'].includes(type) ||
        (type === 'transformation' && canEditTransformationHogCode) ||
        (type === 'destination' && (template?.code_language || hogFunction?.template?.code_language) === 'hog')
    const showTesting = ['destination', 'internal_destination', 'transformation'].includes(type)

    const templateOptionsOverlay = (
        <div className="p-1 max-w-120">
            <p>
                This function was built from the template <b>{hogFunction?.template?.name}</b>.
                {templateHasChanged ? (
                    <>
                        <br />
                        It has different code to the latest version, either due to custom modifications or updates to
                        the template.
                    </>
                ) : null}
            </p>

            <div className="flex flex-1 gap-2 items-center pt-2 border-t">
                <div className="flex-1">
                    <LemonButton>Close</LemonButton>
                </div>

                <LemonButton type="secondary" onClick={() => duplicateFromTemplate()}>
                    New function from template
                </LemonButton>

                {templateHasChanged ? (
                    <LemonButton type="primary" onClick={() => resetToTemplate()}>
                        Reset to template
                    </LemonButton>
                ) : null}
            </div>
        </div>
    )

    return (
        <div className="deprecated-space-y-3">
            <BindLogic logic={hogFunctionConfigurationLogic} props={logicProps}>
                <PageHeader
                    buttons={
                        <>
                            {headerButtons}
                            {saveButtons}
                        </>
                    }
                />

                {hogFunction?.filters?.bytecode_error ? (
                    <div>
                        <LemonBanner type="error">
                            <b>Error saving filters:</b> {hogFunction.filters.bytecode_error}
                        </LemonBanner>
                    </div>
                ) : [
                      'template-google-ads',
                      'template-meta-ads',
                      'template-tiktok-ads',
                      'template-snapchat-ads',
                      'template-linkedin-ads',
                      'template-reddit-pixel',
                      'template-tiktok-pixel',
                      'template-snapchat-pixel',
                      'template-reddit-conversions-api',
                  ].includes(templateId ?? hogFunction?.template?.id ?? '') ||
                  template?.status === 'alpha' ||
                  hogFunction?.template?.status === 'alpha' ? (
                    <div>
                        <LemonBanner type="warning">
                            <p>
                                This destination is currently in an experimental state. For many cases this will work
                                just fine but for others there may be unexpected issues and we do not offer official
                                customer support for it in these cases.
                            </p>
                            {['template-reddit-conversions-api', 'template-snapchat-ads'].includes(
                                templateId ?? hogFunction?.template?.id ?? ''
                            ) ? (
                                <span className="mt-2">
                                    The receiving destination imposes a rate limit of 10 events per second. Exceeding
                                    this limit may result in some events failing to be delivered.
                                </span>
                            ) : null}
                            {['site_destination'].includes(template?.type ?? hogFunction?.template?.type ?? '') ? (
                                <span className="mt-2">
                                    Make sure to enable the `opt_in_site_apps` flag in your `posthog.init` config.
                                </span>
                            ) : null}
                        </LemonBanner>
                    </div>
                ) : null}

                <Form
                    logic={hogFunctionConfigurationLogic}
                    props={logicProps}
                    formKey="configuration"
                    className="deprecated-space-y-3"
                >
                    <div className="flex flex-wrap gap-4 items-start">
                        <div className="flex flex-col flex-1 gap-4 min-w-100">
                            <div className={clsx('p-3 rounded border deprecated-space-y-2 bg-surface-primary')}>
                                <div className="flex flex-row gap-2 items-center min-h-16">
                                    <LemonField name="icon_url">
                                        {({ value, onChange }) => (
                                            <HogFunctionIconEditable
                                                logicKey={id ?? templateId ?? 'new'}
                                                src={value}
                                                onChange={(val) => onChange(val)}
                                            />
                                        )}
                                    </LemonField>

                                    <div className="flex flex-col flex-1 justify-start items-start py-1">
                                        <span className="font-semibold">{configuration.name}</span>
                                        {template && <HogFunctionStatusTag status={template.status} />}
                                    </div>

                                    <HogFunctionStatusIndicator hogFunction={hogFunction} />
                                    <LemonField name="enabled">
                                        {({ value, onChange }) => (
                                            <LemonSwitch
                                                label="Enabled"
                                                onChange={() => onChange(!value)}
                                                checked={value}
                                                disabled={loading}
                                                bordered
                                            />
                                        )}
                                    </LemonField>
                                </div>
                                <LemonField name="name" label="Name">
                                    <LemonInput type="text" disabled={loading} />
                                </LemonField>
                                <LemonField
                                    name="description"
                                    label="Description"
                                    info="Add a description to share context with other team members"
                                >
                                    <LemonTextArea disabled={loading} />
                                </LemonField>

                                {hogFunction?.template?.code_language === 'hog' &&
                                hogFunction?.template &&
                                !hogFunction.template.id.startsWith('template-blank-') ? (
                                    <LemonDropdown showArrow overlay={templateOptionsOverlay}>
                                        <LemonButton
                                            type="tertiary"
                                            size="small"
                                            className="border border-dashed"
                                            fullWidth
                                        >
                                            <span className="flex flex-wrap flex-1 gap-1 items-center">
                                                Built from template:
                                                <span className="font-semibold">{hogFunction?.template.name}</span>
                                                <HogFunctionStatusTag status={hogFunction.template.status} />
                                                <div className="flex-1" />
                                                {templateHasChanged ? (
                                                    <LemonTag type="success">Modified</LemonTag>
                                                ) : null}
                                            </span>
                                        </LemonButton>
                                    </LemonDropdown>
                                ) : null}
                            </div>

                            {type === 'source_webhook' && <HogFunctionSourceWebhookInfo />}

                            {showFilters && <HogFunctionFilters />}

                            {showExpectedVolume ? <HogFunctionEventEstimates /> : null}
                        </div>

                        <div className="deprecated-space-y-4 flex-2 min-w-100">
                            {mightDropEvents && (
                                <div>
                                    <LemonBanner type="info">
                                        <b>Warning:</b> This transformation can filter out events, dropping them
                                        irreversibly. Make sure to double check your configuration, and use filters to
                                        limit the events that this transformation is applied to.
                                    </LemonBanner>
                                </div>
                            )}
                            {aiHogFunctionCreation ? (
                                <MaxTool
                                    name="create_hog_function_inputs"
                                    displayName="Generate and manage input variables"
                                    description="Max can generate and manage input variables for your function"
                                    context={{
                                        current_inputs_schema: configuration.inputs_schema ?? [],
                                        hog_code: configuration.hog ?? '',
                                    }}
                                    callback={(toolOutput: CyclotronJobInputSchemaType[]) => {
                                        // Store the old inputs before changing
                                        setOldInputs(configuration.inputs_schema ?? [])
                                        // Store the new inputs from Max Tool
                                        setNewInputs(toolOutput)
                                        // Report that AI was prompted
                                        reportAIHogFunctionInputsPrompted()
                                        // Don't immediately update the form - let user accept/reject
                                    }}
                                    onMaxOpen={() => {
                                        reportAIHogFunctionInputsPromptOpen()
                                    }}
                                    suggestions={[]}
                                    introOverride={{
                                        headline: 'What input variables do you need?',
                                        description:
                                            'Let me help you generate the input variables for your function based on your code and requirements.',
                                    }}
                                >
                                    <div className={clsx('p-3 rounded border deprecated-space-y-2 bg-surface-primary')}>
                                        <div className="deprecated-space-y-2">
                                            {usesGroups && !hasGroupsAddon ? (
                                                <LemonBanner type="warning">
                                                    <span className="flex gap-2 items-center">
                                                        This function appears to use Groups but you do not have the
                                                        Groups Analytics addon. Without it, you may see empty values
                                                        where you use templates like {'"{groups.kind.properties}"'}
                                                        <PayGateButton
                                                            feature={AvailableFeature.GROUP_ANALYTICS}
                                                            type="secondary"
                                                        />
                                                    </span>
                                                </LemonBanner>
                                            ) : null}

                                            <CyclotronJobInputs
                                                configuration={{
                                                    inputs_schema: newInputs ?? configuration.inputs_schema ?? [],
                                                    inputs: configuration.inputs ?? {},
                                                }}
                                                onInputSchemaChange={(schema) => {
                                                    // If user manually edits while diff is showing, clear the diff
                                                    if (oldInputs && newInputs) {
                                                        clearInputsDiff()
                                                    }
                                                    setConfigurationValue('inputs_schema', schema)
                                                }}
                                                onInputChange={(key, input) => {
                                                    setConfigurationValue(`inputs.${key}`, input)
                                                }}
                                                showSource={showSource}
                                                sampleGlobalsWithInputs={sampleGlobalsWithInputs}
                                            />
                                            {oldInputs && newInputs && (
                                                <div className="flex gap-2 items-center p-2 mt-4 rounded border border-dashed bg-surface-secondary">
                                                    <div className="flex-1 text-center">
                                                        <span className="text-sm font-medium">Suggested by Max</span>
                                                    </div>
                                                    <div className="flex gap-2">
                                                        <LemonButton
                                                            status="danger"
                                                            icon={<IconX />}
                                                            onClick={() => {
                                                                reportAIHogFunctionInputsRejected()
                                                                clearInputsDiff()
                                                            }}
                                                            tooltipPlacement="top"
                                                            size="small"
                                                        >
                                                            Reject
                                                        </LemonButton>
                                                        <LemonButton
                                                            type="tertiary"
                                                            icon={<IconCheck color="var(--success)" />}
                                                            onClick={() => {
                                                                if (newInputs) {
                                                                    setConfigurationValue('inputs_schema', newInputs)
                                                                }
                                                                reportAIHogFunctionInputsAccepted()
                                                                clearInputsDiff()
                                                            }}
                                                            tooltipPlacement="top"
                                                            size="small"
                                                        >
                                                            Accept
                                                        </LemonButton>
                                                    </div>
                                                </div>
                                            )}
                                            {showSource && canEditSource ? (
                                                <LemonButton
                                                    icon={<IconPlus />}
                                                    size="small"
                                                    type="secondary"
                                                    className="my-4"
                                                    onClick={() => {
                                                        setConfigurationValue('inputs_schema', [
                                                            ...(configuration.inputs_schema ?? []),
                                                            {
                                                                type: 'string',
                                                                key: `input_${
                                                                    (configuration.inputs_schema?.length ?? 0) + 1
                                                                }`,
                                                                label: '',
                                                                required: false,
                                                            },
                                                        ])
                                                    }}
                                                >
                                                    Add input variable
                                                </LemonButton>
                                            ) : null}
                                        </div>
                                    </div>
                                </MaxTool>
                            ) : (
                                <div className={clsx('p-3 rounded border deprecated-space-y-2 bg-surface-primary')}>
                                    <div className="deprecated-space-y-2">
                                        {usesGroups && !hasGroupsAddon ? (
                                            <LemonBanner type="warning">
                                                <span className="flex gap-2 items-center">
                                                    This function appears to use Groups but you do not have the Groups
                                                    Analytics addon. Without it, you may see empty values where you use
                                                    templates like {'"{groups.kind.properties}"'}
                                                    <PayGateButton
                                                        feature={AvailableFeature.GROUP_ANALYTICS}
                                                        type="secondary"
                                                    />
                                                </span>
                                            </LemonBanner>
                                        ) : null}

                                        <CyclotronJobInputs
                                            configuration={{
                                                inputs_schema: configuration.inputs_schema ?? [],
                                                inputs: configuration.inputs ?? {},
                                            }}
                                            onInputSchemaChange={(schema) => {
                                                setConfigurationValue('inputs_schema', schema)
                                            }}
                                            onInputChange={(key, input) => {
                                                setConfigurationValue(`inputs.${key}`, input)
                                            }}
                                            showSource={showSource}
                                            sampleGlobalsWithInputs={sampleGlobalsWithInputs}
                                        />
                                        {showSource && canEditSource ? (
                                            <LemonButton
                                                icon={<IconPlus />}
                                                size="small"
                                                type="secondary"
                                                className="my-4"
                                                onClick={() => {
                                                    setConfigurationValue('inputs_schema', [
                                                        ...(configuration.inputs_schema ?? []),
                                                        {
                                                            type: 'string',
                                                            key: `input_${
                                                                (configuration.inputs_schema?.length ?? 0) + 1
                                                            }`,
                                                            label: '',
                                                            required: false,
                                                        },
                                                    ])
                                                }}
                                            >
                                                Add input variable
                                            </LemonButton>
                                        ) : null}
                                    </div>
                                </div>
                            )}

                            <HogFunctionMappings />

                            {canEditSource && (
                                <>
                                    {aiHogFunctionCreation ? (
                                        <MaxTool
                                            name="create_hog_transformation_function"
                                            displayName="Write and tweak Hog code"
                                            description="Max can write and tweak Hog code for you"
                                            context={{
                                                current_hog_code: configuration.hog ?? '',
                                            }}
                                            callback={(toolOutput: string) => {
                                                // Store the old value before changing
                                                setOldHogCode(configuration.hog ?? '')
                                                // Store the new value from Max Tool
                                                setNewHogCode(toolOutput)
                                                // Report that AI was prompted
                                                reportAIHogFunctionPrompted()
                                                // Don't immediately update the form - let user accept/reject
                                            }}
                                            onMaxOpen={() => {
                                                reportAIHogFunctionPromptOpen()
                                            }}
                                            suggestions={[]}
                                            introOverride={{
                                                headline: 'What transformation do you want to create?',
                                                description:
                                                    'Let me help you quickly write the code for your transformation, and tweak it.',
                                            }}
                                        >
                                            <div
                                                ref={sourceCodeRef}
                                                className={clsx(
                                                    'p-3 rounded border deprecated-space-y-2',
                                                    showSource ? 'bg-surface-primary' : 'bg-surface-secondary'
                                                )}
                                            >
                                                <div className="flex gap-2 justify-end items-center">
                                                    <div className="flex-1 deprecated-space-y-2">
                                                        <h2 className="mb-0">Edit source</h2>
                                                        {!showSource ? (
                                                            <p>Click here to edit the function's source code</p>
                                                        ) : null}
                                                    </div>

                                                    {templateHasChanged ? (
                                                        <LemonDropdown showArrow overlay={templateOptionsOverlay}>
                                                            <LemonButton
                                                                type="tertiary"
                                                                size={showSource ? 'xsmall' : 'small'}
                                                                icon={<IconInfo />}
                                                            >
                                                                Modified code
                                                            </LemonButton>
                                                        </LemonDropdown>
                                                    ) : null}

                                                    {!showSource ? (
                                                        <LemonButton
                                                            type="secondary"
                                                            onClick={() => {
                                                                setShowSource(true)
                                                                setTimeout(() => {
                                                                    sourceCodeRef.current?.scrollIntoView({
                                                                        behavior: 'smooth',
                                                                        block: 'start',
                                                                    })
                                                                }, 100)
                                                            }}
                                                            disabledReason={
                                                                // We allow editing the source code for transformations without the Data Pipelines addon
                                                                !hasAddon && type !== 'transformation'
                                                                    ? 'Editing the source code requires the Data Pipelines addon'
                                                                    : undefined
                                                            }
                                                        >
                                                            Edit source code
                                                        </LemonButton>
                                                    ) : (
                                                        <LemonButton
                                                            size="xsmall"
                                                            type="secondary"
                                                            onClick={() => setShowSource(false)}
                                                        >
                                                            Hide source code
                                                        </LemonButton>
                                                    )}
                                                </div>

                                                {showSource ? (
                                                    <LemonField name="hog">
                                                        {({ value, onChange }) => (
                                                            <>
                                                                {!type.startsWith('site_') ? (
                                                                    <span className="text-xs text-secondary">
                                                                        This is the underlying Hog code that will run
                                                                        whenever this triggers.{' '}
                                                                        <Link to="https://posthog.com/docs/hog">
                                                                            See the docs
                                                                        </Link>{' '}
                                                                        for more info
                                                                    </span>
                                                                ) : null}
                                                                {mightDropEvents && (
                                                                    <LemonBanner type="warning" className="mt-2">
                                                                        <b>Warning:</b> Returning null or undefined will
                                                                        drop the event. If this is unintentional, return
                                                                        the event object instead.
                                                                    </LemonBanner>
                                                                )}
                                                                {type === 'source_webhook' && (
                                                                    <LemonBanner type="info" className="mt-2">
                                                                        <b>HTTP requests:</b> Webhook sources can call{' '}
                                                                        <code>postHogCapture</code> to ingest events to
                                                                        PostHog. You can also do HTTP calls with{' '}
                                                                        <code>fetch</code>. In this case however, the
                                                                        request will be queued to a background task, a{' '}
                                                                        <code>201 Created</code> response will be
                                                                        returned and the event will be ingested
                                                                        asynchronously.
                                                                    </LemonBanner>
                                                                )}
                                                                <CodeEditorResizeable
                                                                    language={
                                                                        type.startsWith('site_') ? 'typescript' : 'hog'
                                                                    }
                                                                    value={newHogCode ?? value ?? ''}
                                                                    originalValue={
                                                                        oldHogCode && newHogCode
                                                                            ? oldHogCode
                                                                            : undefined
                                                                    }
                                                                    onChange={(v) => {
                                                                        // If user manually edits while diff is showing, clear the diff
                                                                        if (oldHogCode && newHogCode) {
                                                                            clearHogCodeDiff()
                                                                        }
                                                                        onChange(v ?? '')
                                                                    }}
                                                                    globals={sampleGlobalsWithInputs}
                                                                    showDiffActions={!!(oldHogCode && newHogCode)}
                                                                    onAcceptChanges={() => {
                                                                        if (newHogCode) {
                                                                            onChange(newHogCode)
                                                                        }
                                                                        reportAIHogFunctionAccepted()
                                                                        clearHogCodeDiff()
                                                                    }}
                                                                    onRejectChanges={() => {
                                                                        if (oldHogCode) {
                                                                            onChange(oldHogCode)
                                                                        }
                                                                        reportAIHogFunctionRejected()
                                                                        clearHogCodeDiff()
                                                                    }}
                                                                    options={{
                                                                        minimap: {
                                                                            enabled: false,
                                                                        },
                                                                        wordWrap: 'on',
                                                                        scrollBeyondLastLine: false,
                                                                        automaticLayout: true,
                                                                        fixedOverflowWidgets: true,
                                                                        suggest: {
                                                                            showInlineDetails: true,
                                                                        },
                                                                        quickSuggestionsDelay: 300,
                                                                        readOnly: !!(oldHogCode && newHogCode),
                                                                    }}
                                                                />
                                                            </>
                                                        )}
                                                    </LemonField>
                                                ) : null}
                                            </div>
                                        </MaxTool>
                                    ) : (
                                        <div
                                            ref={sourceCodeRef}
                                            className={clsx(
                                                'p-3 rounded border deprecated-space-y-2',
                                                showSource ? 'bg-surface-primary' : 'bg-surface-secondary'
                                            )}
                                        >
                                            <div className="flex gap-2 justify-end items-center">
                                                <div className="flex-1 deprecated-space-y-2">
                                                    <h2 className="mb-0">Edit source</h2>
                                                    {!showSource ? (
                                                        <p>Click here to edit the function's source code</p>
                                                    ) : null}
                                                </div>

                                                {!showSource ? (
                                                    <LemonButton
                                                        type="secondary"
                                                        onClick={() => {
                                                            setShowSource(true)
                                                            setTimeout(() => {
                                                                sourceCodeRef.current?.scrollIntoView({
                                                                    behavior: 'smooth',
                                                                    block: 'start',
                                                                })
                                                            }, 100)
                                                        }}
                                                        disabledReason={
                                                            // We allow editing the source code for transformations without the Data Pipelines addon
                                                            !hasAddon && type !== 'transformation'
                                                                ? 'Editing the source code requires the Data Pipelines addon'
                                                                : undefined
                                                        }
                                                    >
                                                        Edit source code
                                                    </LemonButton>
                                                ) : (
                                                    <LemonButton
                                                        size="xsmall"
                                                        type="secondary"
                                                        onClick={() => setShowSource(false)}
                                                    >
                                                        Hide source code
                                                    </LemonButton>
                                                )}
                                            </div>

                                            {showSource ? (
                                                <LemonField name="hog">
                                                    {({ value, onChange }) => (
                                                        <>
                                                            {!type.startsWith('site_') ? (
                                                                <span className="text-xs text-secondary">
                                                                    This is the underlying Hog code that will run
                                                                    whenever this triggers.{' '}
                                                                    <Link to="https://posthog.com/docs/hog">
                                                                        See the docs
                                                                    </Link>{' '}
                                                                    for more info
                                                                </span>
                                                            ) : null}
                                                            {mightDropEvents && (
                                                                <LemonBanner type="warning" className="mt-2">
                                                                    <b>Warning:</b> Returning null or undefined will
                                                                    drop the event. If this is unintentional, return the
                                                                    event object instead.
                                                                </LemonBanner>
                                                            )}

                                                            <CodeEditorResizeable
                                                                language={
                                                                    type.startsWith('site_') ? 'typescript' : 'hog'
                                                                }
                                                                value={value ?? ''}
                                                                onChange={(v) => onChange(v ?? '')}
                                                                globals={sampleGlobalsWithInputs}
                                                                options={{
                                                                    minimap: {
                                                                        enabled: false,
                                                                    },
                                                                    wordWrap: 'on',
                                                                    scrollBeyondLastLine: false,
                                                                    automaticLayout: true,
                                                                    fixedOverflowWidgets: true,
                                                                    suggest: {
                                                                        showInlineDetails: true,
                                                                    },
                                                                    quickSuggestionsDelay: 300,
                                                                }}
                                                            />
                                                        </>
                                                    )}
                                                </LemonField>
                                            ) : null}
                                        </div>
                                    )}
                                </>
                            )}
                            {showTesting ? <HogFunctionTest /> : null}
                            {type === 'source_webhook' && <HogFunctionSourceWebhookTest />}
                            <div className="flex gap-2 justify-end">{saveButtons}</div>
                        </div>
                    </div>
                </Form>
            </BindLogic>
        </div>
    )
}
