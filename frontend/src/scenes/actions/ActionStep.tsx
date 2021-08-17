import React from 'react'
import { EventName } from './EventName'
import { AppEditorLink } from 'lib/components/AppEditorLink/AppEditorLink'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { Tooltip } from 'lib/components/Tooltip'
import { URL_MATCHING_HINTS } from 'scenes/actions/hints'
import { Card, Col, Input, Radio, Typography, Space, RadioChangeEvent } from 'antd'
import { ExportOutlined, InfoCircleOutlined } from '@ant-design/icons'
import { ActionStepType } from '~/types'

const { Text } = Typography

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
            <Card className="action-step" style={{ overflow: 'visible' }}>
                {index > 0 && <div className="stateful-badge pos-center-end or">OR</div>}
                <div>
                    {!isOnlyStep && (
                        <div className="remove-wrapper">
                            <button type="button" aria-label="delete" onClick={onDelete}>
                                <span aria-hidden="true">&times;</span>
                            </button>
                        </div>
                    )}
                    <div className="mb">
                        <b>Match Group #{index + 1}</b>
                    </div>
                    {<TypeSwitcher step={step} sendStep={sendStep} />}
                    <div
                        style={{
                            marginTop: step.event === '$pageview' ? 20 : 8,
                            paddingBottom: 0,
                        }}
                    >
                        {step.event === '$autocapture' && (
                            <AutocaptureFields step={step} sendStep={sendStep} actionId={actionId} />
                        )}
                        {step.event != null && step.event !== '$autocapture' && step.event !== '$pageview' && (
                            <div style={{ marginTop: '2rem' }}>
                                <label>
                                    <b>Event name: </b>
                                </label>
                                <EventName
                                    value={step.event}
                                    isActionStep={true}
                                    onChange={(value) =>
                                        sendStep({
                                            ...step,
                                            event: value || '',
                                        })
                                    }
                                />
                            </div>
                        )}
                        {step.event === '$pageview' && (
                            <div>
                                <Option
                                    step={step}
                                    sendStep={sendStep}
                                    item="url"
                                    extra_options={<URLMatching step={step} sendStep={sendStep} />}
                                    label="URL"
                                />
                                {step.url_matching && step.url_matching in URL_MATCHING_HINTS && (
                                    <small style={{ display: 'block', marginTop: -12 }}>
                                        {URL_MATCHING_HINTS[step.url_matching]}
                                    </small>
                                )}
                            </div>
                        )}

                        {step.event && (
                            <div className="property-filters">
                                <h3 className="l3">Filters</h3>
                                {(!step.properties || step.properties.length === 0) && (
                                    <div className="text-muted">This match group has no additional filters.</div>
                                )}
                                <PropertyFilters
                                    propertyFilters={step.properties}
                                    pageKey={identifier}
                                    onChange={(properties) => {
                                        sendStep({
                                            ...step,
                                            properties: properties as [],
                                        })
                                    }}
                                    showConditionBadge
                                />
                            </div>
                        )}
                    </div>
                </div>
            </Card>
        </Col>
    )
}

function Option(props: {
    step: ActionStepType
    sendStep: (stepToSend: ActionStepType) => void
    item: keyof ActionStepType
    label: JSX.Element | string
    placeholder?: string
    caption?: JSX.Element | string
    extra_options?: JSX.Element | string
}): JSX.Element {
    const onOptionChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>): void =>
        props.sendStep({
            ...props.step,
            [props.item]: e.target.value,
        })

    return (
        <div className="mb">
            <label style={{ fontWeight: 'bold' }}>
                {props.label} {props.extra_options}
            </label>
            {props.caption && <div className="action-step-caption">{props.caption}</div>}
            {props.item === 'selector' ? (
                <Input.TextArea
                    allowClear
                    onChange={onOptionChange}
                    value={props.step[props.item] || ''}
                    placeholder={props.placeholder}
                />
            ) : (
                <Input
                    data-attr="edit-action-url-input"
                    allowClear
                    onChange={onOptionChange}
                    value={props.step[props.item] || ''}
                    placeholder={props.placeholder}
                />
            )}
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
    const AndC = (): JSX.Element => {
        return (
            <div className="text-center">
                <span className="stateful-badge and">AND</span>
            </div>
        )
    }
    return (
        <div>
            <span>
                <AppEditorLink actionId={actionId} style={{ margin: '1rem 0' }}>
                    Select element on site <ExportOutlined />
                </AppEditorLink>
                <a
                    href={`${learnMoreLink}#autocapture-based-actions`}
                    target="_blank"
                    rel="noopener"
                    style={{ marginLeft: 8 }}
                >
                    See documentation.
                </a>{' '}
            </span>
            <Option
                step={step}
                sendStep={sendStep}
                item="href"
                label="Link target equals"
                caption={
                    <>
                        If your element is a link, the location that the link opens (<code>href</code> tag)
                    </>
                }
            />
            <AndC />
            <Option
                step={step}
                sendStep={sendStep}
                item="text"
                label="Text equals"
                caption="Text content inside your element"
            />
            <AndC />
            <Option
                step={step}
                sendStep={sendStep}
                item="selector"
                label={
                    <>
                        HTML selector matches
                        <Tooltip title="Click here to learn more about supported selectors">
                            <a href={`${learnMoreLink}#matching-selectors`} target="_blank" rel="noopener">
                                <InfoCircleOutlined style={{ marginLeft: 4 }} />
                            </a>
                        </Tooltip>
                    </>
                }
                placeholder='button[data-attr="my-id"]'
                caption={
                    <Space direction="vertical">
                        <Text style={{ color: 'var(--muted)' }}>
                            CSS selector or an HTML attribute that ideally uniquely identifies your element. Example:{' '}
                            <Text code>[data-attr="signup"]</Text>
                        </Text>
                    </Space>
                }
            />
            <div style={{ marginBottom: 18 }}>
                <AndC />
            </div>
            <Option
                step={step}
                sendStep={sendStep}
                item="url"
                extra_options={<URLMatching step={step} sendStep={sendStep} />}
                label="Page URL"
                caption="Elements will match only when triggered from the URL (particularly useful if you have non-unique elements in different pages)."
            />
            {step?.url_matching && step.url_matching in URL_MATCHING_HINTS && (
                <small style={{ display: 'block', marginTop: -12 }}>{URL_MATCHING_HINTS[step.url_matching]}</small>
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
            sendStep({ ...step, event: '' })
        } else if (type === '$pageview') {
            sendStep({
                ...step,
                event: '$pageview',
                url: step.url,
            })
        }
    }

    return (
        <div className={`type-switcher${step.event === undefined ? ' unselected' : ''}`}>
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

function URLMatching({
    step,
    sendStep,
}: {
    step: ActionStepType
    sendStep: (stepToSend: ActionStepType) => void
}): JSX.Element {
    const handleURLMatchChange = (e: RadioChangeEvent): void => {
        sendStep({ ...step, url_matching: e.target.value })
    }
    return (
        <Radio.Group
            buttonStyle="solid"
            onChange={handleURLMatchChange}
            value={step.url_matching || 'contains'}
            size="small"
        >
            <Radio.Button value="contains">contains</Radio.Button>
            <Radio.Button value="regex">matches regex</Radio.Button>
            <Radio.Button value="exact">matches exactly</Radio.Button>
        </Radio.Group>
    )
}
