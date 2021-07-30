import React, { Component } from 'react'
import { EventName } from './EventName'
import { AppEditorLink } from 'lib/components/AppEditorLink/AppEditorLink'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import PropTypes from 'prop-types'
import { URL_MATCHING_HINTS } from 'scenes/actions/hints'
import { Card, Col, Input, Radio, Typography, Space, Tooltip } from 'antd'
const { Text } = Typography
import { ExportOutlined, InfoCircleOutlined } from '@ant-design/icons'

const learnMoreLink = 'https://posthog.com/docs/user-guides/actions?utm_medium=in-product&utm_campaign=action-page'

export class ActionStep extends Component {
    constructor(props) {
        super(props)
        this.state = {
            step: props.step,
        }
        this.AutocaptureFields = this.AutocaptureFields.bind(this)
    }
    sendStep = (step) => {
        this.props.onChange(step)
    }
    Option = (props) => {
        let onChange = (e) => {
            this.sendStep({ ...this.props.step, [props.item]: e.target.value })
        }

        return (
            <div className="mb">
                <label style={{ fontWeight: 'bold' }}>
                    {props.label} {props.extra_options}
                </label>
                {props.caption && <div className="action-step-caption">{props.caption}</div>}
                {props.item === 'selector' ? (
                    <Input.TextArea
                        allowClear
                        onChange={onChange}
                        value={this.props.step[props.item] || ''}
                        placeholder={props.placeholder}
                    />
                ) : (
                    <Input
                        data-attr="edit-action-url-input"
                        allowClear
                        onChange={onChange}
                        value={this.props.step[props.item] || ''}
                        placeholder={props.placeholder}
                    />
                )}
            </div>
        )
    }
    TypeSwitcher = () => {
        let { step } = this.props
        const handleChange = (e) => {
            const type = e.target.value
            if (type === '$autocapture') {
                this.sendStep({ ...step, event: '$autocapture' })
            } else if (type === 'event') {
                this.sendStep({ ...step, event: '' })
            } else if (type === '$pageview') {
                this.sendStep({
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
    AutocaptureFields({ step, actionId }) {
        const AndC = () => {
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
                <this.Option
                    item="href"
                    label="Link target equals"
                    caption={
                        <>
                            If your element is a link, the location that the link opens (<code>href</code> tag)
                        </>
                    }
                    selector={this.state.element && 'a[href="' + this.state.element.getAttribute('href') + '"]'}
                />
                <AndC />
                <this.Option item="text" label="Text equals" caption="Text content inside your element" />
                <AndC />
                <this.Option
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
                    selector={step.selector}
                    placeholder='button[data-attr="my-id"]'
                    caption={
                        <Space direction="vertical">
                            <Text style={{ color: 'var(--muted)' }}>
                                CSS selector or an HTML attribute that ideally uniquely identifies your element.
                                Example: <Text code>[data-attr="signup"]</Text>
                            </Text>
                        </Space>
                    }
                />
                <div style={{ marginBottom: 18 }}>
                    <AndC />
                </div>
                <this.Option
                    item="url"
                    extra_options={<this.URLMatching step={step} />}
                    label="Page URL"
                    caption="Elements will match only when triggered from the URL (particularly useful if you have non-unique elements in different pages)."
                />
                {step?.url_matching && step.url_matching in URL_MATCHING_HINTS && (
                    <small style={{ display: 'block', marginTop: -12 }}>{URL_MATCHING_HINTS[step.url_matching]}</small>
                )}
            </div>
        )
    }
    URLMatching = ({ step }) => {
        const handleURLMatchChange = (e) => {
            this.sendStep({ ...step, url_matching: e.target.value })
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
    render() {
        let { step, actionId, isOnlyStep, index, identifier, onDelete } = this.props

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
                            <b>Match Group #{this.props.index + 1}</b>
                        </div>
                        {<this.TypeSwitcher />}
                        <div
                            style={{
                                marginTop: step.event === '$pageview' ? 20 : 8,
                                paddingBottom: 0,
                            }}
                        >
                            {step.event === '$autocapture' && (
                                <this.AutocaptureFields step={step} actionId={actionId} />
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
                                            this.sendStep({
                                                ...step,
                                                event: value || '',
                                            })
                                        }
                                    />
                                </div>
                            )}
                            {step.event === '$pageview' && (
                                <div>
                                    <this.Option
                                        item="url"
                                        extra_options={<this.URLMatching step={step} />}
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
                                            this.sendStep({
                                                ...this.props.step, // Not sure why, but the normal 'step' variable does not work here
                                                properties,
                                            })
                                        }}
                                        showConditionBadges
                                    />
                                </div>
                            )}
                        </div>
                    </div>
                </Card>
            </Col>
        )
    }
}
ActionStep.propTypes = {
    step: PropTypes.object,
    index: PropTypes.number.isRequired,
}
