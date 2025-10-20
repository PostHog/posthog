import clsx from 'clsx'
import { BindLogic, useValues } from 'kea'
import { Form } from 'kea-forms'

import {
    LemonBanner,
    LemonButton,
    LemonDropdown,
    LemonLabel,
    LemonSwitch,
    LemonTag,
    SpinnerOverlay,
} from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { hogFunctionConfigurationLogic } from 'scenes/hog-functions/configuration/hogFunctionConfigurationLogic'
import { HogFunctionFilters } from 'scenes/hog-functions/filters/HogFunctionFilters'
import { HogFunctionMappings } from 'scenes/hog-functions/mapping/HogFunctionMappings'
import { HogFunctionEventEstimates } from 'scenes/hog-functions/metrics/HogFunctionEventEstimates'

import { humanizeHogFunctionType } from '../hog-function-utils'
import { HogFunctionStatusIndicator } from '../misc/HogFunctionStatusIndicator'
import { HogFunctionStatusTag } from '../misc/HogFunctionStatusTag'
import { HogFunctionTest } from './HogFunctionTest'
import { HogFunctionCode } from './components/HogFunctionCode'
import {
    HogFunctionConfigurationClearChangesButton,
    HogFunctionConfigurationSaveButton,
} from './components/HogFunctionConfigurationButtons'
import { HogFunctionInputs } from './components/HogFunctionInputs'
import { HogFunctionSourceWebhookInfo } from './components/HogFunctionSourceWebhookInfo'
import { HogFunctionSourceWebhookTest } from './components/HogFunctionSourceWebhookTest'
import { HogFunctionTemplateOptions } from './components/HogFunctionTemplateOptions'

export interface HogFunctionConfigurationProps {
    templateId?: string | null
    id?: string | null
    logicKey?: string
}

export function HogFunctionConfiguration({ templateId, id, logicKey }: HogFunctionConfigurationProps): JSX.Element {
    const logicProps = { templateId, id, logicKey }
    const logic = hogFunctionConfigurationLogic(logicProps)
    const {
        configuration,
        loading,
        loaded,
        hogFunction,
        template,
        templateHasChanged,
        type,
        mightDropEvents,
        showFilters,
        showExpectedVolume,
        canEditSource,
        showTesting,
    } = useValues(logic)

    if (loading && !loaded) {
        return <SpinnerOverlay />
    }

    if (!loaded) {
        return <NotFound object="Hog function" />
    }

    const templateInfo =
        hogFunction?.template?.code_language === 'hog' &&
        hogFunction?.template &&
        !hogFunction.template.id.startsWith('template-blank-') ? (
            <LemonDropdown showArrow overlay={<HogFunctionTemplateOptions />}>
                <LemonButton type="tertiary" size="small" className="border border-dashed" fullWidth>
                    <span className="flex flex-wrap flex-1 gap-1 items-center">
                        Built from template:
                        <span className="font-semibold">{hogFunction?.template.name}</span>
                        <HogFunctionStatusTag status={hogFunction.template.status} />
                        <div className="flex-1" />
                        {templateHasChanged ? <LemonTag type="success">Modified</LemonTag> : null}
                    </span>
                </LemonButton>
            </LemonDropdown>
        ) : null

    return (
        <div className="deprecated-space-y-3">
            <BindLogic logic={hogFunctionConfigurationLogic} props={logicProps}>
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
                                This {humanizeHogFunctionType(type)} is currently in an experimental state. For many
                                cases this will work just fine but for others there may be unexpected issues and we do
                                not offer official customer support for it in these cases.
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
                                <div className="flex items-center justify-between">
                                    <LemonLabel>Status</LemonLabel>
                                    {hogFunction && <HogFunctionStatusIndicator hogFunction={hogFunction} />}
                                </div>
                                <LemonField name="enabled">
                                    {({ value, onChange }) => (
                                        <LemonSwitch
                                            onChange={() => onChange(!value)}
                                            checked={value}
                                            disabled={loading}
                                            bordered
                                            fullWidth
                                            label={
                                                <span className="flex flex-1">
                                                    {configuration.enabled ? 'Enabled' : 'Disabled'}
                                                </span>
                                            }
                                            tooltip={
                                                <>
                                                    {value
                                                        ? 'Enabled. Events will be processed.'
                                                        : 'Disabled. Events will not be processed.'}
                                                </>
                                            }
                                        />
                                    )}
                                </LemonField>

                                {templateInfo}
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
                            <HogFunctionInputs />

                            <HogFunctionMappings />

                            {canEditSource && <HogFunctionCode />}
                            {showTesting ? <HogFunctionTest /> : null}
                            {type === 'source_webhook' && <HogFunctionSourceWebhookTest />}
                            <div className="flex gap-2 justify-end">
                                <HogFunctionConfigurationClearChangesButton />
                                <HogFunctionConfigurationSaveButton />
                            </div>
                        </div>
                    </div>
                </Form>
            </BindLogic>
        </div>
    )
}
