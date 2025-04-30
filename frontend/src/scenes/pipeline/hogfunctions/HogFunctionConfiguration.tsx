import { IconPlus } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDivider,
    LemonDropdown,
    LemonInput,
    LemonLabel,
    LemonSwitch,
    LemonTag,
    LemonTextArea,
    Link,
    SpinnerOverlay,
} from '@posthog/lemon-ui'
import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { combineUrl } from 'kea-router'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { PayGateButton } from 'lib/components/PayGateMini/PayGateButton'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'
import { HogFunctionBroadcastDelivery } from 'products/messaging/frontend/HogFunctionCustomConfiguration/HogFunctionBroadcastDelivery'
import { useEffect, useState } from 'react'
import { useRef } from 'react'
import { urls } from 'scenes/urls'

import { AvailableFeature } from '~/types'

import { DestinationTag } from '../destinations/DestinationTag'
import { HogFunctionFilters } from './filters/HogFunctionFilters'
import { hogFunctionConfigurationLogic, mightDropEvents } from './hogFunctionConfigurationLogic'
import { HogFunctionIconEditable } from './HogFunctionIcon'
import { HogFunctionInputs } from './HogFunctionInputs'
import { HogFunctionStatusIndicator } from './HogFunctionStatusIndicator'
import { HogFunctionTest } from './HogFunctionTest'
import { HogFunctionMappings } from './mapping/HogFunctionMappings'
import { HogFunctionEventEstimates } from './metrics/HogFunctionEventEstimates'
export interface HogFunctionConfigurationProps {
    templateId?: string | null
    id?: string | null
    logicKey?: string

    displayOptions?: {
        embedded?: boolean
        hidePageHeader?: boolean
        hideOverview?: boolean
        showFilters?: boolean
        showExpectedVolume?: boolean
        showStatus?: boolean
        showEnabled?: boolean
        showTesting?: boolean
        hideTestingConfiguration?: boolean
        canEditSource?: boolean
        showPersonsCount?: boolean
    }
}

export function HogFunctionConfiguration({
    templateId,
    id,
    logicKey,
    displayOptions = {},
}: HogFunctionConfigurationProps): JSX.Element {
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
        globalsWithInputs,
        showPaygate,
        hasAddon,
        personsCount,
        personsCountLoading,
        personsListQuery,
        template,
        templateHasChanged,
        type,
        usesGroups,
        hasGroupsAddon,
    } = useValues(logic)

    // State for debounced mightDropEvents check
    const [mightDrop, setMightDrop] = useState(false)
    const [debouncedCode, setDebouncedCode] = useState('')

    // Debounce the code check
    useEffect(() => {
        if (type !== 'transformation' || !configuration?.hog) {
            setMightDrop(false)
            return
        }

        const hogCode = configuration.hog || ''

        const timeoutId = setTimeout(() => {
            if (debouncedCode !== hogCode) {
                setDebouncedCode(hogCode)
                setMightDrop(mightDropEvents(hogCode))
            }
        }, 500)

        return () => clearTimeout(timeoutId)
    }, [configuration?.hog, type, debouncedCode])

    const {
        submitConfiguration,
        resetForm,
        setShowSource,
        duplicate,
        resetToTemplate,
        duplicateFromTemplate,
        setConfigurationValue,
        deleteHogFunction,
    } = useActions(logic)
    const canEditTransformationHogCode = useFeatureFlag('HOG_TRANSFORMATIONS_CUSTOM_HOG_ENABLED')
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

    const embedded = displayOptions.embedded ?? false
    const includeHeaderButtons = !(displayOptions.hidePageHeader ?? false)
    const showOverview = !(displayOptions.hideOverview ?? false)
    const showFilters =
        displayOptions.showFilters ??
        ['destination', 'internal_destination', 'site_destination', 'broadcast', 'email', 'transformation'].includes(
            type
        )
    const showExpectedVolume =
        displayOptions.showExpectedVolume ?? ['destination', 'site_destination', 'transformation'].includes(type)
    const showStatus =
        displayOptions.showStatus ?? ['destination', 'internal_destination', 'email', 'transformation'].includes(type)
    const showEnabled =
        displayOptions.showEnabled ??
        [
            'destination',
            'internal_destination',
            'email',
            'site_destination',
            'site_app',
            'transformation',
            'broadcast',
        ].includes(type)
    const canEditSource =
        displayOptions.canEditSource ??
        // Never allow editing for legacy plugins
        (!isLegacyPlugin &&
            (['destination', 'email', 'site_destination', 'site_app'].includes(type) ||
                (type === 'transformation' && canEditTransformationHogCode)))
    const showPersonsCount = displayOptions.showPersonsCount ?? ['broadcast'].includes(type)
    const showTesting =
        displayOptions.showTesting ?? ['destination', 'internal_destination', 'transformation', 'email'].includes(type)

    const showLeftPanel = showOverview || showExpectedVolume || showPersonsCount || showFilters

    return (
        <div className="deprecated-space-y-3">
            <BindLogic logic={hogFunctionConfigurationLogic} props={logicProps}>
                {includeHeaderButtons && (
                    <PageHeader
                        buttons={
                            <>
                                {headerButtons}
                                {saveButtons}
                            </>
                        }
                    />
                )}

                {hogFunction?.filters?.bytecode_error ? (
                    <div>
                        <LemonBanner type="error">
                            <b>Error saving filters:</b> {hogFunction.filters.bytecode_error}
                        </LemonBanner>
                    </div>
                ) : ['template-reddit-conversions-api', 'template-snapchat-ads'].includes(templateId ?? '') ? (
                    <div>
                        <LemonBanner type="warning">
                            The receiving destination imposes a rate limit of 10 events per second. Exceeding this limit
                            may result in some events failing to be delivered.
                        </LemonBanner>
                    </div>
                ) : null}

                <Form
                    logic={hogFunctionConfigurationLogic}
                    props={logicProps}
                    formKey="configuration"
                    className="deprecated-space-y-3"
                >
                    <div className="flex flex-wrap items-start gap-4">
                        {showLeftPanel && (
                            <div className="flex flex-col flex-1 gap-4 min-w-100">
                                <div
                                    className={clsx(
                                        'p-3 deprecated-space-y-2 bg-surface-primary',
                                        !embedded && 'border rounded'
                                    )}
                                >
                                    <div className="flex flex-row items-center gap-2 min-h-16">
                                        <LemonField name="icon_url">
                                            {({ value, onChange }) => (
                                                <HogFunctionIconEditable
                                                    logicKey={id ?? templateId ?? 'new'}
                                                    src={value}
                                                    onChange={(val) => onChange(val)}
                                                />
                                            )}
                                        </LemonField>

                                        <div className="flex flex-col items-start justify-start flex-1 py-1">
                                            <span className="font-semibold">{configuration.name}</span>
                                            {template && <DestinationTag status={template.status} />}
                                        </div>

                                        {showStatus && <HogFunctionStatusIndicator hogFunction={hogFunction} />}
                                        {showEnabled && (
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
                                        )}
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

                                    {isLegacyPlugin ? null : hogFunction?.template &&
                                      !hogFunction.template.id.startsWith('template-blank-') ? (
                                        <LemonDropdown
                                            showArrow
                                            overlay={
                                                <div className="p-1 max-w-120">
                                                    <p>
                                                        This function was built from the template{' '}
                                                        <b>{hogFunction.template.name}</b>. If the template is updated,
                                                        this function is not affected unless you choose to update it.
                                                    </p>

                                                    <div className="flex items-center flex-1 gap-2 pt-2 border-t">
                                                        <div className="flex-1">
                                                            <LemonButton>Close</LemonButton>
                                                        </div>

                                                        <LemonButton
                                                            type="secondary"
                                                            onClick={() => duplicateFromTemplate()}
                                                        >
                                                            New function from template
                                                        </LemonButton>

                                                        {templateHasChanged ? (
                                                            <LemonButton
                                                                type="primary"
                                                                onClick={() => resetToTemplate()}
                                                            >
                                                                Update
                                                            </LemonButton>
                                                        ) : null}
                                                    </div>
                                                </div>
                                            }
                                        >
                                            <div className="text-xs border border-dashed rounded text-secondary">
                                                <Link subtle className="flex flex-wrap items-center gap-1 p-2">
                                                    Built from template:
                                                    <span className="font-semibold">{hogFunction?.template.name}</span>
                                                    <DestinationTag status={hogFunction.template.status} />
                                                    {templateHasChanged ? (
                                                        <LemonTag type="success">Update available!</LemonTag>
                                                    ) : null}
                                                </Link>
                                            </div>
                                        </LemonDropdown>
                                    ) : null}
                                </div>

                                {showFilters && <HogFunctionFilters />}

                                {showPersonsCount && (
                                    <div className="relative p-3 deprecated-space-y-2 border rounded bg-surface-primary">
                                        <div>
                                            <LemonLabel>Matching persons</LemonLabel>
                                        </div>
                                        {personsCount && !personsCountLoading ? (
                                            <>
                                                Found{' '}
                                                <Link
                                                    to={
                                                        // TODO: swap for a link to the persons page
                                                        combineUrl(urls.activity(), {}, { q: personsListQuery }).url
                                                    }
                                                    target="_blank"
                                                >
                                                    <strong>
                                                        {personsCount ?? 0} {personsCount !== 1 ? 'people' : 'person'}
                                                    </strong>
                                                </Link>{' '}
                                                to send to.
                                            </>
                                        ) : personsCountLoading ? (
                                            <div className="min-h-20">
                                                <SpinnerOverlay />
                                            </div>
                                        ) : (
                                            <p>The expected volume could not be calculated</p>
                                        )}
                                    </div>
                                )}

                                {showExpectedVolume ? <HogFunctionEventEstimates /> : null}
                            </div>
                        )}

                        <div className="deprecated-space-y-4 flex-2 min-w-100">
                            {type === 'transformation' && mightDrop && (
                                <div>
                                    <LemonBanner type="warning">
                                        <b>Warning:</b> This transformation will drop events. If this is not intended,
                                        please adjust your transformation code to return events instead of dropping
                                        them.
                                    </LemonBanner>
                                </div>
                            )}
                            <div
                                className={clsx(
                                    'p-3 deprecated-space-y-2 bg-surface-primary',
                                    !embedded && 'border rounded'
                                )}
                            >
                                <div className="deprecated-space-y-2">
                                    {usesGroups && !hasGroupsAddon ? (
                                        <LemonBanner type="warning">
                                            <span className="flex items-center gap-2">
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

                                    <HogFunctionInputs
                                        configuration={configuration}
                                        setConfigurationValue={setConfigurationValue}
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
                                                        key: `input_${(configuration.inputs_schema?.length ?? 0) + 1}`,
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

                            <HogFunctionMappings />

                            {canEditSource && (
                                <div
                                    ref={sourceCodeRef}
                                    className={clsx(
                                        'border rounded p-3 deprecated-space-y-2',
                                        showSource ? 'bg-surface-primary' : 'bg-surface-secondary'
                                    )}
                                >
                                    <div className="flex items-center justify-end gap-2">
                                        <div className="flex-1 deprecated-space-y-2">
                                            <h2 className="mb-0">Edit source</h2>
                                            {!showSource ? <p>Click here to edit the function's source code</p> : null}
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
                                                    !hasAddon
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
                                                            This is the underlying Hog code that will run whenever the
                                                            filters match.{' '}
                                                            <Link to="https://posthog.com/docs/hog">See the docs</Link>{' '}
                                                            for more info
                                                        </span>
                                                    ) : null}
                                                    {type === 'transformation' && mightDrop && (
                                                        <LemonBanner type="warning" className="mt-2">
                                                            <b>Warning:</b> Returning null or undefined will drop the
                                                            event. If this is unintentional, return the event object
                                                            instead.
                                                        </LemonBanner>
                                                    )}
                                                    <CodeEditorResizeable
                                                        language={type.startsWith('site_') ? 'typescript' : 'hog'}
                                                        value={value ?? ''}
                                                        onChange={(v) => onChange(v ?? '')}
                                                        globals={globalsWithInputs}
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
                            {showTesting ? (
                                <HogFunctionTest configurable={!displayOptions.hideTestingConfiguration} />
                            ) : null}
                            {type === 'broadcast' && <HogFunctionBroadcastDelivery />}
                            <div className="flex justify-end gap-2">{saveButtons}</div>
                        </div>
                    </div>
                </Form>
            </BindLogic>
        </div>
    )
}
