import { IconPlus } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDivider,
    LemonDropdown,
    LemonInput,
    LemonLabel,
    LemonSelect,
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
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { Sparkline } from 'lib/components/Sparkline'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'
import { urls } from 'scenes/urls'

import { AvailableFeature } from '~/types'

import { DestinationTag } from '../destinations/DestinationTag'
import { HogFunctionFilters } from './filters/HogFunctionFilters'
import { hogFunctionConfigurationLogic } from './hogFunctionConfigurationLogic'
import { HogFunctionIconEditable } from './HogFunctionIcon'
import { HogFunctionInputs } from './HogFunctionInputs'
import { HogFunctionStatusIndicator } from './HogFunctionStatusIndicator'
import { HogFunctionTest, HogFunctionTestPlaceholder } from './HogFunctionTest'

const EVENT_THRESHOLD_ALERT_LEVEL = 8000

export interface HogFunctionConfigurationProps {
    templateId?: string | null
    id?: string | null
}

export function HogFunctionConfiguration({ templateId, id }: HogFunctionConfigurationProps): JSX.Element {
    const logicProps = { templateId, id }
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
        sparkline,
        sparklineLoading,
        personsCount,
        personsCountLoading,
        personsListQuery,
        template,
        subTemplate,
        templateHasChanged,
        forcedSubTemplateId,
        type,
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
        setSubTemplateId,
    } = useActions(logic)

    if (loading && !loaded) {
        return <SpinnerOverlay />
    }

    if (!loaded) {
        return <NotFound object="Hog function" />
    }

    const headerButtons = (
        <>
            {!templateId && (
                <>
                    <More
                        overlay={
                            <>
                                <LemonButton fullWidth onClick={() => duplicate()}>
                                    Duplicate
                                </LemonButton>
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

    const showFilters = type === 'destination' || type === 'broadcast'
    const showExpectedVolume = type === 'destination'
    const showEnabled = type === 'destination' || type === 'email'
    const canEditSource = type === 'destination' || type === 'email'
    const showPersonsCount = type === 'broadcast'

    return (
        <div className="space-y-3">
            <BindLogic logic={hogFunctionConfigurationLogic} props={logicProps}>
                <PageHeader
                    buttons={
                        <>
                            {headerButtons}
                            {saveButtons}
                        </>
                    }
                />

                {type === 'destination' ? (
                    <LemonBanner type="info">
                        Hog Functions are in <b>beta</b> and are the next generation of our data pipeline destinations.
                        You can use pre-existing templates or modify the source Hog code to create your own custom
                        functions.
                    </LemonBanner>
                ) : null}

                {hogFunction?.filters?.bytecode_error ? (
                    <div>
                        <LemonBanner type="error">
                            <b>Error saving filters:</b> {hogFunction.filters.bytecode_error}
                        </LemonBanner>
                    </div>
                ) : null}

                <Form
                    logic={hogFunctionConfigurationLogic}
                    props={logicProps}
                    formKey="configuration"
                    className="space-y-3"
                >
                    <div className="flex flex-wrap gap-4 items-start">
                        <div className="flex flex-col gap-4 flex-1 min-w-100">
                            <div className="border bg-bg-light rounded p-3 space-y-2">
                                <div className="flex flex-row gap-2 min-h-16 items-center">
                                    <LemonField name="icon_url">
                                        {({ value, onChange }) => (
                                            <HogFunctionIconEditable
                                                logicKey={id ?? templateId ?? 'new'}
                                                src={value}
                                                onChange={(val) => onChange(val)}
                                            />
                                        )}
                                    </LemonField>

                                    <div className="flex flex-col items-start py-1 flex-1 justify-start">
                                        <span className="font-semibold">{configuration.name}</span>
                                        {template && <DestinationTag status={template.status} />}
                                    </div>

                                    {showEnabled && <HogFunctionStatusIndicator hogFunction={hogFunction} />}
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

                                {hogFunction?.template ? (
                                    <LemonDropdown
                                        showArrow
                                        overlay={
                                            <div className="max-w-120 p-1">
                                                <p>
                                                    This function was built from the template{' '}
                                                    <b>{hogFunction.template.name}</b>. If the template is updated, this
                                                    function is not affected unless you choose to update it.
                                                </p>

                                                <div className="flex flex-1 gap-2 items-center border-t pt-2">
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
                                                        <LemonButton type="primary" onClick={() => resetToTemplate()}>
                                                            Update
                                                        </LemonButton>
                                                    ) : null}
                                                </div>
                                            </div>
                                        }
                                    >
                                        <div className="border border-dashed rounded text-muted-alt text-xs">
                                            <Link subtle className="flex items-center gap-1 flex-wrap p-2">
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
                                <div className="relative border bg-bg-light rounded p-3 space-y-2">
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

                            {showExpectedVolume && (
                                <div className="relative border bg-bg-light rounded p-3 space-y-2">
                                    <LemonLabel>Expected volume</LemonLabel>
                                    {sparkline && !sparklineLoading ? (
                                        <>
                                            {sparkline.count > EVENT_THRESHOLD_ALERT_LEVEL ? (
                                                <LemonBanner type="warning">
                                                    <b>Warning:</b> This destination would have triggered{' '}
                                                    <strong>
                                                        {sparkline.count ?? 0} time{sparkline.count !== 1 ? 's' : ''}
                                                    </strong>{' '}
                                                    in the last 7 days. Consider the impact of this function on your
                                                    destination.
                                                </LemonBanner>
                                            ) : (
                                                <p>
                                                    This destination would have triggered{' '}
                                                    <strong>
                                                        {sparkline.count ?? 0} time{sparkline.count !== 1 ? 's' : ''}
                                                    </strong>{' '}
                                                    in the last 7 days.
                                                </p>
                                            )}
                                            <Sparkline
                                                type="bar"
                                                className="w-full h-20"
                                                data={sparkline.data}
                                                labels={sparkline.labels}
                                            />
                                        </>
                                    ) : sparklineLoading ? (
                                        <div className="min-h-20">
                                            <SpinnerOverlay />
                                        </div>
                                    ) : (
                                        <p>The expected volume could not be calculated</p>
                                    )}
                                </div>
                            )}
                        </div>

                        <div className="flex-2 min-w-100 space-y-4">
                            {!forcedSubTemplateId && template?.sub_templates && (
                                <>
                                    <div className="border bg-bg-light rounded p-3 space-y-2">
                                        <div className="flex items-center gap-2">
                                            <LemonLabel className="flex-1">Choose template</LemonLabel>
                                            <LemonSelect
                                                size="small"
                                                options={[
                                                    {
                                                        value: null,
                                                        label: 'Default',
                                                    },
                                                    ...template.sub_templates.map((subTemplate) => ({
                                                        value: subTemplate.id,
                                                        label: subTemplate.name,
                                                        labelInMenu: (
                                                            <div className="max-w-120 space-y-1 my-1">
                                                                <div className="font-semibold">{subTemplate.name}</div>
                                                                <div className="text-muted font-sans text-xs">
                                                                    {subTemplate.description}
                                                                </div>
                                                            </div>
                                                        ),
                                                    })),
                                                ]}
                                                value={subTemplate?.id}
                                                onChange={(value) => {
                                                    setSubTemplateId(value)
                                                }}
                                            />
                                        </div>
                                    </div>
                                </>
                            )}

                            <div className="border bg-bg-light rounded p-3 space-y-2">
                                <div className="space-y-2">
                                    <HogFunctionInputs />
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

                            {canEditSource && (
                                <div
                                    className={clsx(
                                        'border rounded p-3 space-y-2',
                                        showSource ? 'bg-bg-light' : 'bg-accent-3000'
                                    )}
                                >
                                    <div className="flex items-center gap-2 justify-end">
                                        <div className="flex-1 space-y-2">
                                            <h2 className="mb-0">Edit source</h2>
                                            {!showSource ? <p>Click here to edit the function's source code</p> : null}
                                        </div>

                                        {!showSource ? (
                                            <LemonButton
                                                type="secondary"
                                                onClick={() => setShowSource(true)}
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
                                                    <span className="text-xs text-muted-alt">
                                                        This is the underlying Hog code that will run whenever the
                                                        filters match.{' '}
                                                        <Link to="https://posthog.com/docs/hog">See the docs</Link> for
                                                        more info
                                                    </span>
                                                    <CodeEditorResizeable
                                                        language="hog"
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

                            {!id || id === 'new' ? <HogFunctionTestPlaceholder /> : <HogFunctionTest id={id} />}
                            <div className="flex gap-2 justify-end">{saveButtons}</div>
                        </div>
                    </div>
                </Form>
            </BindLogic>
        </div>
    )
}
