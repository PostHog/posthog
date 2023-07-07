import { LemonEventName } from './EventName'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { URL_MATCHING_HINTS } from 'scenes/actions/hints'
import { Col, Radio, RadioChangeEvent } from 'antd'
import { ActionStepType, StringMatching } from '~/types'
import { LemonButton, LemonInput, Link } from '@posthog/lemon-ui'
import { IconClose, IconOpenInApp } from 'lib/lemon-ui/icons'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { useState } from 'react'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

const learnMoreLink = 'https://posthog.com/docs/user-guides/actions?utm_medium=in-product&utm_campaign=action-page'

interface Props {
    step: ActionStepType
    actionId: number
    isOnlyStep: boolean
    index: number
    identifier: string
    onDelete: () => void
    onChange: (step: ActionStepType) => void
}

export function ActionStep({ step, actionId, isOnlyStep, index, identifier, onDelete, onChange }: Props): JSX.Element {
    const sendStep = (stepToSend: ActionStepType): void => {
        onChange(stepToSend)
    }

    return (
        <Col span={24} md={12}>
            <div className="rounded border p-4 relative h-full">
                {index > 0 && <div className="stateful-badge pos-center-end or">OR</div>}
                <div className="space-y-4">
                    <div className="flex items-center justify-between">
                        <b>Match Group #{index + 1}</b>

                        {!isOnlyStep && (
                            <LemonButton
                                status="primary-alt"
                                icon={<IconClose />}
                                size="small"
                                aria-label="delete"
                                onClick={onDelete}
                            />
                        )}
                    </div>
                    {<TypeSwitcher step={step} sendStep={sendStep} />}

                    {step.event === '$autocapture' && (
                        <AutocaptureFields step={step} sendStep={sendStep} actionId={actionId} />
                    )}
                    {step.event !== undefined && step.event !== '$autocapture' && step.event !== '$pageview' && (
                        <div className="space-y-1">
                            <LemonLabel>Event name</LemonLabel>
                            <LemonEventName
                                value={step.event}
                                onChange={(value) =>
                                    sendStep({
                                        ...step,
                                        event: value,
                                    })
                                }
                                placeholder="All events"
                                allEventsOption="explicit"
                            />

                            <small>
                                <Link to="https://posthog.com/docs/libraries" target="_blank">
                                    See documentation
                                </Link>{' '}
                                on how to send custom events in lots of languages.
                            </small>
                        </div>
                    )}
                    {step.event === '$pageview' && (
                        <div>
                            <Option
                                step={step}
                                sendStep={sendStep}
                                item="url"
                                extra_options={<StringMatchingSelection field="url" step={step} sendStep={sendStep} />}
                                label="URL"
                            />
                            {step.url_matching && step.url_matching in URL_MATCHING_HINTS && (
                                <small>{URL_MATCHING_HINTS[step.url_matching]}</small>
                            )}
                        </div>
                    )}

                    <div className="mt-4 space-y-2">
                        <LemonLabel>Filters</LemonLabel>
                        <PropertyFilters
                            propertyFilters={step.properties}
                            pageKey={identifier}
                            eventNames={step.event ? [step.event] : []}
                            onChange={(properties) => {
                                sendStep({
                                    ...step,
                                    properties: properties as [],
                                })
                            }}
                            showConditionBadge
                        />
                    </div>
                </div>
            </div>
        </Col>
    )
}

/**
 * There are several issues with how autocapture actions are matched. See https://github.com/PostHog/posthog/issues/7333
 *
 * Until they are fixed this validator can be used to guide users to working solutions
 */
const validateSelector = (val: string, selectorPrompts: (s: JSX.Element | null) => void): void => {
    if (val.includes('#')) {
        selectorPrompts(
            <>
                PostHog actions don't support the <code>#example</code> syntax.
                <br />
                Use the equivalent <code>[id="example"]</code> instead.
            </>
        )
    } else {
        selectorPrompts(null)
    }
}

function Option({
    step,
    sendStep,
    item,
    label,
    placeholder = 'Specify a value to match on this',
    caption,
    extra_options,
}: {
    step: ActionStepType
    sendStep: (stepToSend: ActionStepType) => void
    item: keyof Pick<ActionStepType, 'href' | 'text' | 'selector' | 'url'>
    label: JSX.Element | string
    placeholder?: string
    caption?: JSX.Element | string
    extra_options?: JSX.Element | string
}): JSX.Element {
    const [selectorPrompt, setSelectorPrompt] = useState(null as JSX.Element | null)

    const onOptionChange = (val: string): void => {
        if (item === 'selector') {
            validateSelector(val, setSelectorPrompt)
        }
        sendStep({
            ...step,
            [item]: val || null, // "" is a valid filter, we don't want it
        })
    }

    return (
        <div className="space-y-1">
            <LemonLabel>
                {label} {extra_options}
            </LemonLabel>
            {caption && <div className="action-step-caption">{caption}</div>}
            <LemonInput
                data-attr="edit-action-url-input"
                allowClear
                onChange={onOptionChange}
                value={step[item] || ''}
                placeholder={placeholder}
            />
            {item === 'selector' && selectorPrompt && <LemonBanner type="warning">{selectorPrompt}</LemonBanner>}
        </div>
    )
}

const AndSeparator = (): JSX.Element => {
    return (
        <div className="text-center my-2">
            <span className="stateful-badge and">AND</span>
        </div>
    )
}

function AutocaptureFields({
    step,
    actionId,
    sendStep,
}: {
    step: ActionStepType
    sendStep: (stepToSend: ActionStepType) => void
    actionId: number
}): JSX.Element {
    const onSelectElement = (): void => {
        LemonDialog.open({
            title: 'Select an element',
            description: actionId
                ? 'Choose the domain on which to edit this action'
                : 'Choose the domain on which to create this action',
            content: (
                <>
                    <AuthorizedUrlList actionId={actionId} type={AuthorizedUrlListType.TOOLBAR_URLS} />
                </>
            ),
            primaryButton: {
                children: 'Close',
                type: 'secondary',
            },
        })
    }
    return (
        <div className="space-y-4">
            <div className="flex items-center gap-2">
                <LemonButton size="small" type="secondary" onClick={onSelectElement} sideIcon={<IconOpenInApp />}>
                    Select element on site
                </LemonButton>
                <Link to={`${learnMoreLink}#autocapture-based-actions`} target="_blank">
                    See documentation.
                </Link>
            </div>
            <Option
                step={step}
                sendStep={sendStep}
                item="text"
                extra_options={<StringMatchingSelection field="text" step={step} sendStep={sendStep} />}
                label="Element text"
            />
            <AndSeparator />
            <Option
                step={step}
                sendStep={sendStep}
                item="href"
                extra_options={<StringMatchingSelection field="href" step={step} sendStep={sendStep} />}
                label="Element link target"
                caption={
                    <>
                        Filtering by the <code>href</code> attribute. Only <code>{'<a/>'}</code> elements will be
                        matched.
                    </>
                }
            />
            <AndSeparator />
            <Option
                step={step}
                sendStep={sendStep}
                item="selector"
                label="Element matches HTML selector"
                caption={
                    <span>
                        The selector can be a tag name, class, HTML attribute, or all of those combined. Example:{' '}
                        <code>button[data-attr="signup"]</code>.{' '}
                        <Link to={`${learnMoreLink}#matching-selectors`}>Learn more in Docs.</Link>
                    </span>
                }
            />
            <AndSeparator />
            <Option
                step={step}
                sendStep={sendStep}
                item="url"
                extra_options={<StringMatchingSelection field="url" step={step} sendStep={sendStep} />}
                label="Page URL"
                caption="The page on which the interaction occurred."
            />
            {step?.url_matching && step.url_matching in URL_MATCHING_HINTS && (
                <small>{URL_MATCHING_HINTS[step.url_matching]}</small>
            )}
        </div>
    )
}

function TypeSwitcher({
    step,
    sendStep,
}: {
    step: ActionStepType
    sendStep: (stepToSend: ActionStepType) => void
}): JSX.Element {
    const handleChange = (e: RadioChangeEvent): void => {
        const type = e.target.value
        if (type === '$autocapture') {
            sendStep({ ...step, event: '$autocapture' })
        } else if (type === 'event') {
            sendStep({ ...step, event: null })
        } else if (type === '$pageview') {
            sendStep({
                ...step,
                event: '$pageview',
                url: step.url,
            })
        }
    }

    return (
        <div className="type-switcher">
            <Radio.Group
                buttonStyle="solid"
                onChange={handleChange}
                value={
                    step.event === '$autocapture' || step.event === '$pageview' || step.event === undefined
                        ? step.event
                        : 'event'
                }
            >
                <Radio.Button value="$autocapture">Autocapture</Radio.Button>
                <Radio.Button value="event">Custom event</Radio.Button>
                <Radio.Button value="$pageview">Page view</Radio.Button>
            </Radio.Group>
        </div>
    )
}

function StringMatchingSelection({
    field,
    step,
    sendStep,
}: {
    field: 'url' | 'text' | 'href'
    step: ActionStepType
    sendStep: (stepToSend: ActionStepType) => void
}): JSX.Element {
    const key = `${field}_matching`
    const handleURLMatchChange = (e: RadioChangeEvent): void => {
        sendStep({ ...step, [key]: e.target.value })
    }
    const defaultValue = field === 'url' ? StringMatching.Contains : StringMatching.Exact
    return (
        <Radio.Group buttonStyle="solid" onChange={handleURLMatchChange} value={step[key] || defaultValue} size="small">
            <Radio.Button value="exact">matches exactly</Radio.Button>
            <Radio.Button value="regex">matches regex</Radio.Button>
            <Radio.Button value="contains">contains</Radio.Button>
        </Radio.Group>
    )
}
